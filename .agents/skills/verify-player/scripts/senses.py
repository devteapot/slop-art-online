#!/usr/bin/env python3
"""What the player's character senses, as the rules say (`my_senses`, docs/INTERFACE.md, "What
was agreed" 8): the world's `senses(a)` law with all the character's facts, written to a private
`character_senses` row only when a value changes, read through the `my_senses` view.

1. After `join`, `my_senses` holds one row, the player's character's, with the law's sight and
   hearing (by day 11 m, at night 6, with a torch at night 9; speech 9 m), and no field.
2. Nothing changes for 6 s: the row is not written again (`at_ms` and every value stay).
3. The admin turns the world's `fov_on` law on (`set_world_law`): the row follows within 2 s,
   with the field's numbers (focal 70°, side 110°, a third, near 3 m or 2 m in the dark,
   margin 10°) and a later `at_ms`. Turned off again: no field, its numbers 0.
4. At night only (the world's clock decides; skipped by day): a torch in the pack changes the
   sight from 6 m to 9 m.
5. Another identity (the bystander, joined) reads only its own row; the owner sees one
   `character_senses` row per played character.

    senses.py --run RUN

Needs `verify.py launch --run RUN` (any seed with the shipped senses law). Admin calls set the
scene only: `set_world_law`, `grant_items`. Writes `RUN/senses.json`. Python standard library
only.
"""

import argparse
import importlib.util
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("appraise", HERE / "appraise.py")
A = importlib.util.module_from_spec(spec)
spec.loader.exec_module(A)
V = A.V

RESULTS = A.RESULTS
EVIDENCE = {}


def mine(p, who="player"):
    return p.sql("SELECT * FROM my_senses", who)


def law(p, name, value):
    return p.call("set_world_law", [name, json.dumps(value)], "admin")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run", required=True)
    a = ap.parse_args()
    p = A.P(a.run)
    me = p.me("player", "Senser")
    try:
        # 1. The row after joining. A call hands the character back if the minds took it over
        # (no call for `takeover_s`); its first frame then brings a row left from before up to date.
        time.sleep(1.0)
        rows = A.wait_for(lambda: mine(p), 5)
        EVIDENCE["joined"] = rows
        r = rows[0] if len(rows) == 1 else None
        A.check(p, "my_senses: one row, my character's", r is not None and r["id"] == me, rows)
        A.check(p, "my_senses: the shipped law's sight (11, 6 or 9 m) and hearing (9 m), no field",
                r and r["sight"] in (11.0, 6.0, 9.0) and r["hearing"] == 9.0 and not r["field"] and r["focal_deg"] == 0.0, r)
        # 2. Written only on change.
        time.sleep(6)
        later = mine(p)
        EVIDENCE["steady"] = later
        A.check(p, "nothing changed in 6 s: the row was not written again (same at_ms and values)", later == rows, {"before": rows, "after": later})
        # 3. The field on and off.
        code, out = law(p, "fov_on", True)
        on = A.wait_for(lambda: [x for x in mine(p) if x["field"]], 3)
        EVIDENCE["fov_on"] = {"call": [code, out.strip()[:200]], "rows": on}
        f = on[0] if on else None
        A.check(p, "fov_on: the row follows within 3 s with the field's numbers",
                code == 200 and f and f["focal_deg"] == 70.0 and f["side_deg"] == 110.0 and abs(f["side_share"] - 0.3333) < 1e-3
                and f["near_m"] in (3.0, 2.0) and f["margin_deg"] == 10.0 and f["at_ms"] > r["at_ms"], f)
        code, out = law(p, "fov_on", False)
        off = A.wait_for(lambda: [x for x in mine(p) if not x["field"]], 3)
        EVIDENCE["fov_off"] = {"call": [code, out.strip()[:200]], "rows": off}
        g = off[0] if off else None
        A.check(p, "fov_on off again: no field, its numbers 0, sight as before",
                code == 200 and g and g["focal_deg"] == 0.0 and g["near_m"] == 0.0 and g["sight"] == r["sight"] and g["at_ms"] > f["at_ms"], g)
        # 4. A torch at night.
        now = mine(p)[0]
        if now["sight"] == 6.0:
            p.call("grant_items", [me, "torch", 1], "admin")
            lit = A.wait_for(lambda: [x for x in mine(p) if x["sight"] == 9.0], 3)
            EVIDENCE["torch"] = lit
            A.check(p, "at night a torch in the pack: sight 6 m to 9 m", lit, lit)
        else:
            EVIDENCE["torch"] = f"skipped: sight {now['sight']} m (day, or a torch already carried)"
        # 5. Scoped to the caller.
        other = p.me("bystander", "SenserTwo")
        theirs = A.wait_for(lambda: mine(p, "bystander"), 5)
        owner = p.sql("SELECT id FROM character_senses", "admin")
        played = [c["id"] for c in p.sql("SELECT id FROM presence", "admin")]
        EVIDENCE["scoped"] = {"bystander": theirs, "player": mine(p), "owner": owner, "played": played}
        A.check(p, "the bystander reads only its own row", [x["id"] for x in theirs] == [other] and [x["id"] for x in mine(p)] == [me], EVIDENCE["scoped"])
        A.check(p, "the owner's character_senses: one row per played character", sorted(x["id"] for x in owner) == sorted(played) and {me, other} <= {x["id"] for x in owner}, EVIDENCE["scoped"])
        # 6. A death takes the row away.
        p.call("kill", [other, "verify senses"], "admin")
        gone = A.wait_for(lambda: not [x for x in p.sql("SELECT id FROM character_senses", "admin") if x["id"] == other], 3)
        EVIDENCE["death"] = {"owner": p.sql("SELECT id FROM character_senses", "admin"), "bystander": mine(p, "bystander")}
        A.check(p, "a death removes the character's row; its view is empty", gone and not EVIDENCE["death"]["bystander"], EVIDENCE["death"])
    finally:
        law(p, "fov_on", False)
        finish(p)


def finish(p):
    (V.run_dir(p.st["run"]) / "senses.json").write_text(json.dumps({"checks": RESULTS, "evidence": EVIDENCE}, indent=1) + "\n")
    failed = [r for r in RESULTS if not r["ok"]]
    print(f"{len(RESULTS) - len(failed)} of {len(RESULTS)} passed")
    for r in RESULTS:
        print(("PASS " if r["ok"] else "FAIL ") + r["check"])
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
