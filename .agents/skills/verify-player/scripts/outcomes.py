#!/usr/bin/env python3
"""How the player's acts and death came out, in codes (`my_act_outcomes`, docs/PERCEPTION.md,
"Act outcomes"; docs/INTERFACE.md, "What was agreed" 4): one private `act_outcome` row per
experience line that tells an outcome, keyed by the line's id and written in the same
transaction, so a client draws a note or the death screen without parsing English.

1. A deliberate act the skill's check refuses (eat berries with none): an `act` row, not ok,
   code `check`, skill `eat`, the check's words in `why`; its id is the `act` line's in
   `my_experience`.
2. The same act done (berries granted): ok, code `done`, `why` empty.
3. A moment skill as a one-shot graph the rules refuse (`graze`, "only grazing animals graze"):
   an `own` row, not ok, with the refusal's code.
4. Bounded: 70 refused acts in a row leave at most `frame::LINES_SHOWN` (64) rows, each one's
   line still in `my_experience`.
5. Scoped: the bystander (a second identity, joined) reads none of mine; anonymous none.
6. Death (admin `kill` with its own cause): a `death` row, code `other`, its line "You died
   (…)." in `my_experience`; the death screen reads them until the person joins again.
7. Joining again: the dead character's rows go (`set_player`).

    outcomes.py --run RUN

Needs `verify.py launch --run RUN` (the default `world`). Admin calls set the scene only:
`grant_items`, `kill`. Writes `RUN/outcomes.json`. Python standard library only.
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


def outcomes(p, who="player"):
    return sorted(p.sql("SELECT * FROM my_act_outcomes", who), key=lambda r: r["id"])


def lines(p, who="player"):
    return {r["id"]: r for r in p.sql("SELECT id, kind, text, observer FROM my_experience", who)}


def anonymous(p, q):
    code, body = V.http(f"/v1/database/{p.db}/sql", q, None, raw=True)
    return code, body.strip()[:200]


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run", required=True)
    a = ap.parse_args()
    p = A.P(a.run)
    me = p.me("player", "Outcome")
    try:
        def newest(after, pred=lambda r: True, secs=6):
            got = A.wait_for(lambda: [r for r in outcomes(p) if r["id"] > after and pred(r)], secs)
            return got[-1] if got else None

        base = max([r["id"] for r in outcomes(p)] or [0])
        # 1. Refused by the skill's check.
        p.call("human_act", [json.dumps({"do": {"skill": "eat", "item": "berries"}})])
        r1 = newest(base)
        l1 = A.wait_for(lambda: lines(p).get(r1["id"]) if r1 else None, 3)
        EVIDENCE["refused"] = {"row": r1, "line": l1}
        A.check(p, "refused act: an act row, not ok, code check, skill eat, the check's words; keyed by its act line",
                r1 and r1["kind"] == "act" and not r1["ok"] and r1["code"] == "check" and r1["skill"] == "eat" and r1["why"]
                and r1["observer"] == me and l1 and l1["kind"] == "act" and r1["why"] in l1["text"], EVIDENCE["refused"])
        # 2. Done.
        p.call("grant_items", [me, "berries", 2], "admin")
        p.call("human_act", [json.dumps({"do": {"skill": "eat", "item": "berries"}})])
        r2 = newest(r1["id"] if r1 else base, lambda r: r["ok"], 10)
        EVIDENCE["done"] = r2
        A.check(p, "done act: ok, code done, skill eat, why empty", r2 and r2["kind"] == "act" and r2["code"] == "done" and r2["skill"] == "eat" and r2["why"] == "", r2)
        # 3. A graph's refused action, told to the person.
        last = max([r["id"] for r in outcomes(p)] or [0])
        p.call("human_act", [json.dumps({"do": "graze"})])
        r3 = newest(last, lambda r: r["kind"] == "own")
        # The row is written with the line; the line reaches my_experience at the next release
        # (at most 100 ms later), so a client joins the two by id.
        EVIDENCE["own"] = {"row": r3, "line": A.wait_for(lambda: lines(p).get(r3["id"]) if r3 else None, 3)}
        A.check(p, "a refused one-shot graph: an own row, not ok, a refusal code, skill graze",
                r3 and not r3["ok"] and r3["code"] in ("check", "refused") and r3["skill"] == "graze" and EVIDENCE["own"]["line"], EVIDENCE["own"])
        # 4. Bounded with the lines.
        for _ in range(70):
            p.call("human_act", [json.dumps({"do": {"skill": "eat", "item": "fish"}})])
        time.sleep(2)
        rows, ls = outcomes(p), lines(p)
        owner = [r for r in p.sql(f"SELECT id FROM act_outcome WHERE observer = {me}", "admin")]
        EVIDENCE["bounded"] = {"rows": len(rows), "owner_rows": len(owner), "lines": len(ls), "orphans": [r["id"] for r in rows if r["id"] not in ls]}
        A.check(p, "70 refused acts: at most 64 rows, every one's line still in my_experience",
                0 < len(rows) <= 64 and len(owner) == len(rows) and not EVIDENCE["bounded"]["orphans"], EVIDENCE["bounded"])
        # 5. Scoped.
        other = p.me("bystander", "OutcomeTwo")
        theirs = outcomes(p, "bystander")
        anon = anonymous(p, "SELECT * FROM act_outcome")
        EVIDENCE["scoped"] = {"bystander": theirs, "anonymous_table": anon, "anonymous_view": anonymous(p, "SELECT * FROM my_act_outcomes")}
        A.check(p, "the bystander reads none of mine; act_outcome is refused to anonymous",
                all(r["observer"] == other for r in theirs) and anon[0] != 200, EVIDENCE["scoped"])
        # 6. Death.
        last = max([r["id"] for r in outcomes(p)] or [0])
        p.call("kill", [me, "verify outcomes"], "admin")
        r6 = newest(last, lambda r: r["kind"] == "death")
        l6 = A.wait_for(lambda: lines(p).get(r6["id"]) if r6 else None, 3)
        EVIDENCE["death"] = {"row": r6, "line": l6, "my_characters": p.sql("SELECT id, alive, cause FROM my_characters", "player")}
        A.check(p, "death: a death row, code other, its line 'You died (verify outcomes).' in my_experience",
                r6 and r6["code"] == "other" and not r6["ok"] and r6["observer"] == me and l6 and l6["kind"] == "death" and l6["text"] == "You died (verify outcomes).", EVIDENCE["death"])
        # 7. Joining again.
        p.call("join", ["OutcomeAgain"], "player")
        left = A.wait_for(lambda: not p.sql(f"SELECT id FROM act_outcome WHERE observer = {me}", "admin"), 3)
        EVIDENCE["rejoin"] = {"owner_rows_of_dead": p.sql(f"SELECT id FROM act_outcome WHERE observer = {me}", "admin"), "mine": outcomes(p)}
        A.check(p, "joining again: the dead character's rows are gone", left and all(r["observer"] != me for r in EVIDENCE["rejoin"]["mine"]), EVIDENCE["rejoin"])
    finally:
        finish(p)


def finish(p):
    (V.run_dir(p.st["run"]) / "outcomes.json").write_text(json.dumps({"checks": RESULTS, "evidence": EVIDENCE}, indent=1) + "\n")
    failed = [r for r in RESULTS if not r["ok"]]
    print(f"{len(RESULTS) - len(failed)} of {len(RESULTS)} passed")
    for r in RESULTS:
        print(("PASS " if r["ok"] else "FAIL ") + r["check"])
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
