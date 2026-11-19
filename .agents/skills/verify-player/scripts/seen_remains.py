#!/usr/bin/env python3
"""A player at a field sees every remains structure and receives no noticing lines."""

import argparse
import importlib.util
import json
import math
import time
from pathlib import Path
from types import SimpleNamespace

from appraise import P, V, RESULTS, check

ROOT = Path(__file__).resolve().parents[4]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True)
    p = P(parser.parse_args().run)
    spec = importlib.util.spec_from_file_location("core_scenes", ROOT / ".agents/skills/verify-core/scripts/scenes.py")
    core = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(core)
    at = core.clear_line(SimpleNamespace(rows=p.sql))[5]

    def admin(reducer, *args):
        code, body = p.call(reducer, list(args), "admin")
        if code != 200:
            raise RuntimeError(f"{reducer}: {code} {body}")

    player = p.me("player", "Fieldwalker")
    before = {row["id"] for row in p.sql("SELECT id FROM character")}
    admin("spawn_crowd", 20, True)
    dead = sorted(row["id"] for row in p.sql("SELECT id FROM character") if row["id"] not in before)
    for i, who in enumerate(dead):
        admin("place_at", who, at[0] + 1 + i % 5, at[1] + i // 5 % 3 - 1)
        admin("kill", who, "player remains fixture")
    field = {r["id"] for r in p.sql("SELECT * FROM structure WHERE kind = 'remains'") if r["owner"] in dead}
    admin("place_at", player, *at)
    # Several looks pass at the field before the reads: a played character still runs no noticing.
    time.sleep(5)
    body = p.sql("SELECT * FROM my_body", "player")[0]
    remains = p.sql("SELECT * FROM structure WHERE kind = 'remains'", "player")
    nearby = {r["id"] for r in remains if math.dist((body["x"], body["y"]), (r["x"], r["y"])) <= 6}
    heard = p.sql("SELECT * FROM my_experience", "player")
    noticing = [r for r in heard if r["text"].startswith("You notice")]
    check(p, "field has twenty bodies in reach of the player", len(field) == 20 and field <= nearby, sorted(field & nearby))
    check(p, "player has no noticing lines", not noticing, noticing)
    code, _ = V.http(f"/v1/database/{p.db}/sql", "SELECT * FROM seen_structures", p.token("player"), raw=True)
    check(p, "player cannot read the private rows", code in (400, 401, 403), code)
    out = ROOT / ".local/living/verify" / p.st["run"]
    (out / "seen-remains.json").write_text(json.dumps({"checks": RESULTS, "structures": remains, "experience": heard}, indent=2))
    return 0 if all(r["ok"] for r in RESULTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
