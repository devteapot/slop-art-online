#!/usr/bin/env python3
"""The player's statuses as the game shows them (its pills, `living/game/src/ui/live.rs`
`my_body`): the installed script's `status_of` over the player's own `my_vitals` row, worked out
the way a client does (`living-rules` example `status_check`: `BodyFacts::of` and `status_of`, by
the script's parts, `status_parts`, docs/STATUS_PARTS.md), equal to the whole law's answer.

1. The player joins. Its `my_vitals` row (read with its own identity) and the installed `script`
   row (public) give a status list by the parts that is the whole law's, by day and at night.
2. The admin sets the body (fixtures, not a player's act: `admin_set_vitals` for health, owner SQL
   for hunger and energy): badly hurt, very hungry, exhausted. The player's row follows; the parts
   give `very_hungry`, `exhausted`, `badly_hurt`, `slowed`, the same as the whole law, and the
   pills are the statuses whose tone is not plain.
3. Set well again (health full, fed, well rested): `fed`, `well_rested`, `unhurt`, the same both
   ways, and no bad pill.

    status.py --run RUN

Needs `verify.py launch --run RUN` (default seed). Builds the `living-rules` example
`status_check` with cargo in `$CARGO_TARGET_DIR`. Writes `RUN/status.json`. Python standard
library only.
"""

import argparse
import importlib.util
import json
import os
import subprocess
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
STAGES = {0: "infant", 1: "child", 3: "elder"}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run", required=True)
    a = ap.parse_args()
    p = A.P(a.run)
    target = Path(os.environ.get("CARGO_TARGET_DIR") or V.LIVING / "target")
    subprocess.run(["cargo", "build", "-q", "-p", "living-rules", "--example", "status_check"], cwd=V.LIVING, check=True)
    me = p.me("player", "Bodied")
    try:
        script = V.run_dir(a.run) / "status-script.rhai"
        script.write_text(p.sql("SELECT source FROM script WHERE name = 'skills'", "player")[0]["source"])
        day_ms = p.sql("SELECT day_ms FROM world", "admin")[0]["day_ms"]

        def statuses(label, night):
            row = A.wait_for(lambda: p.sql("SELECT * FROM my_vitals", "player"), 5)
            char = [c for c in p.sql("SELECT id, kind, stage FROM my_characters", "player") if c["id"] == me][0]
            now = p.sql("SELECT last_ms FROM clock", "admin")[0]["last_ms"]
            facts = {"kind": char["kind"], "stage": STAGES.get(char["stage"], "adult"), "night": night, "now_ms": now, "row": row[0]}
            out = json.loads(subprocess.run([str(target / "debug/examples/status_check"), str(script), str(day_ms), json.dumps(facts)], capture_output=True, text=True, check=True).stdout)
            EVIDENCE[label] = {"my_vitals": row, "facts": facts, "client": out}
            return out

        # 1. As joined.
        for night in (False, True):
            s = statuses(f"joined-{'night' if night else 'day'}", night)
            A.check(p, f"as joined ({'night' if night else 'day'}): the parts give the whole law's statuses", s["same"] and s["parts"] and len(s["declared"]) == 8, s)
        # 2. Hurt, hungry, exhausted.
        p.call("admin_set_vitals", [me, 25.0], "admin")
        now = p.sql("SELECT last_ms FROM clock", "admin")[0]["last_ms"]
        code, body = V.http(f"/v1/database/{p.db}/sql", f"UPDATE vitals SET hunger = 85.0, energy = 5.0, at_ms = {now}, rate_key = 0 WHERE id = {me}", p.token("admin"), raw=True)
        A.check(p, "fixture: hunger and energy set by owner SQL", code == 200, body[:200])
        time.sleep(1.0)
        s = statuses("low", False)
        want = {"very_hungry", "exhausted", "badly_hurt", "slowed"}
        A.check(p, "badly hurt, very hungry, exhausted: those statuses and slowed, the same both ways", s["same"] and want <= set(s["parts"]), s)
        A.check(p, "the pills are the statuses that are not plain", want <= set(s["pills"]), s)
        # 3. Well again.
        p.call("admin_set_vitals", [me, 1000.0], "admin")
        now = p.sql("SELECT last_ms FROM clock", "admin")[0]["last_ms"]
        V.http(f"/v1/database/{p.db}/sql", f"UPDATE vitals SET hunger = 10.0, energy = 95.0, at_ms = {now}, rate_key = 0 WHERE id = {me}", p.token("admin"), raw=True)
        time.sleep(1.0)
        s = statuses("well", False)
        A.check(p, "well again: fed, well rested, unhurt, the same both ways, no bad pill",
                s["same"] and {"fed", "well_rested", "unhurt"} <= set(s["parts"]) and not ({"very_hungry", "exhausted", "badly_hurt", "slowed"} & set(s["pills"])), s)
    finally:
        finish(p)


def finish(p):
    (V.run_dir(p.st["run"]) / "status.json").write_text(json.dumps({"checks": RESULTS, "evidence": EVIDENCE}, indent=1) + "\n")
    failed = [r for r in RESULTS if not r["ok"]]
    print(f"{len(RESULTS) - len(failed)} of {len(RESULTS)} passed")
    for r in RESULTS:
        print(("PASS " if r["ok"] else "FAIL ") + r["check"])
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
