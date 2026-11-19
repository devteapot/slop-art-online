#!/usr/bin/env python3
"""Measure whether a seated resident moves when its graph is replaced (no mind service)."""

import argparse
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "verify/scripts"))
import verify


def measure(run):
    if not run.startswith("core-rest-latch-"):
        raise ValueError("use a dedicated core-rest-latch-* scratch run")
    state = verify.load(run)
    if not state.get("published") or state["db"] != f"verify-{run}":
        raise ValueError("launch the scratch world with verify.py before driving it")
    if state.get("server_url", verify.URL) != verify.URL:
        raise ValueError("use the server that owns the scratch world")

    token = verify.admin_token()
    base = f"/v1/database/{state['db']}"

    def request(path, data, raw=False):
        code, body = verify.http(base + path, data, token, raw=raw)
        if code != 200:
            raise RuntimeError(f"{path}: {code} {body}")
        return body

    def rows(query):
        table = json.loads(request("/sql", query, raw=True))[-1]
        names = [col["name"]["some"] for col in table["schema"]["elements"]]
        return [dict(zip(names, row)) for row in table["rows"]]

    def install(actor, skill):
        request("/call/set_behavior", [actor, json.dumps({"do": skill})])

    def snapshot(actor):
        clock = rows("SELECT last_ms FROM clock")[0]["last_ms"]
        body = rows(f"SELECT x, y, t_ms, vx, vy FROM body WHERE id = {actor}")[0]
        activities = rows(
            f"SELECT skill, phase, node, revision, started_ms, ends_ms FROM activity WHERE id = {actor}"
        )
        return {"clock_ms": clock, "body": body, "activity": next(iter(activities), None)}

    actor = min(
        row["id"] for row in rows("SELECT id, name, kind, alive, ai FROM character")
        if row["kind"] == "person" and row["alive"] and row["ai"]
    )
    ticks_before = rows("SELECT ticks FROM stats")[0]["ticks"]
    install(actor, "rest")
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        seated = snapshot(actor)
        act = seated["activity"]
        if (act and act["skill"] == "rest" and act["phase"] == 1
                and seated["clock_ms"] - act["started_ms"] >= 3100
                and act["ends_ms"] - seated["clock_ms"] >= 1000
                and seated["body"]["vx"] == seated["body"]["vy"] == 0):
            break
        time.sleep(0.1)
    else:
        raise RuntimeError(f"resident did not settle into rest: {seated}")

    start = time.monotonic()
    install(actor, "wander")
    brain = rows(f"SELECT * FROM brain WHERE id = {actor}")[0]
    if brain["revision"] <= act["revision"] or "wander" not in brain["graph"]:
        raise RuntimeError(f"wander graph was not installed: {brain}")

    out = verify.run_dir(run)
    move = None
    with (out / "rest-latch-samples.jsonl").open("w") as samples:
        while True:
            sample = snapshot(actor)
            wall_s = time.monotonic() - start
            samples.write(json.dumps({"wall_s": wall_s, **sample}) + "\n")
            body = sample["body"]
            if (body["x"], body["y"]) != (seated["body"]["x"], seated["body"]["y"]):
                move = sample
                break
            if wall_s >= 47:
                break
            time.sleep(0.1)

    ticks_after = rows("SELECT ticks FROM stats")[0]["ticks"]
    result = {
        "actor": actor,
        "ticks_before": ticks_before,
        "ticks_after": ticks_after,
        "seated": seated,
        "installed": brain,
        "first_move": move,
        "first_move_observed_wall_s": round(wall_s, 3) if move else None,
        "observation_wall_s": round(wall_s, 3),
    }
    (out / "rest-latch-result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    if ticks_after <= ticks_before or sample["clock_ms"] <= seated["clock_ms"]:
        raise RuntimeError("scratch world did not advance")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True)
    measure(parser.parse_args().run)
