#!/usr/bin/env python3
"""Public-feed scoping as a real client receives it (docs/FEED_SCOPING.md, "Authority shapes").

    feed_scope.py --run client-feed-...   (a run launched with verify.py launch, any seed)

The admin turns the `feed_scope_on` law on with `feed_scope_grace_s` 1, and the world goes to
stage 2 (the legacy public `structure`, `gate` and `resource_node` rows emptied, the canonical rows
private). The player joins (its own identity); a second player joins with another. A remains is
staged far beyond the player's sight and a storage beside the second player.

Through the Rust SDK probe (`drive.py --query`, WebSocket) and HTTP SQL:
- the nonowner cannot select the private canonical or copy tables (`structure_held`,
  `gate_held`, `resource_held`, `thing_seen`, `remembered_thing`, `owner_seen`, `fuel_seen`) by
  SQL or by subscription, anonymous or as a player, and the legacy public tables are empty;
- its `my_things` lacks the unseen remains and the second player's storage, while the owner's
  truth (`structure_held`, `thing_seen`) has the remains, and the second player's copy of its
  storage, as a control;
- brought beside the remains, the player's live subscription receives it in `my_things`
  (presence only: kind and place); a new connection with the same identity gets it in its first
  result (the stored copy is the reconnect snapshot), and its `my_remembered_things` too;
- `feed_scope`, `map_structure` and `map_resource` are public, and `map_structure` has
  architecture only.
Writes `RUN/feed-*.jsonl` and `RUN/feed_scope.json`. Python standard library only.
"""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / ".agents/skills/verify/scripts"))
import verify as v  # noqa: E402

DRIVE = ROOT / ".agents/skills/verify-client/scripts/drive.py"
MAP_KINDS = {"shelter", "house", "hall", "workshop", "market", "inn", "smokehouse", "furnace", "gate"}
PRIVATE = ("structure_held", "gate_held", "resource_held", "thing_seen", "remembered_thing", "owner_seen", "fuel_seen", "owned_by", "lot_door", "id_seq", "seen_structures_scoped")


def run(*args, check=True):
    r = subprocess.run([sys.executable, *map(str, args)], capture_output=True, text=True, cwd=ROOT, timeout=300)
    if check and r.returncode:
        raise RuntimeError(f"{args[:3]}: {r.stderr[-400:] or r.stdout[-400:]}")
    return r


def opt(x):
    """An Option as SATS JSON gives it ({"some": v} / {"none": ...}, or [tag, v]) as v or None."""
    if isinstance(x, dict):
        return x.get("some") if "some" in x else None
    if isinstance(x, list) and len(x) == 2 and isinstance(x[0], int):
        return x[1] if x[0] == 0 else None
    return x


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", required=True)
    rid = ap.parse_args().run
    out = ROOT / ".local/living/verify" / rid
    st = v.load(rid)
    db = st["db"]
    owner = v.admin_token()
    checks = {}

    def check(name, ok, detail=None):
        checks[name] = {"passed": bool(ok), "detail": detail}
        print(("PASS " if ok else "FAIL ") + name, flush=True)

    def sql(query, token):
        code, body = v.http(f"/v1/database/{db}/sql", query, token, raw=True)
        if code != 200:
            return None
        res = json.loads(body)[-1]
        fields = [c["name"]["some"] for c in res["schema"]["elements"]]
        return [dict(zip(fields, r)) for r in res["rows"]]

    def call(reducer, args, token=owner):
        code, body = v.http(f"/v1/database/{db}/call/{reducer}", args, token, timeout=90)
        if code != 200:
            raise RuntimeError((reducer, code, body))

    def stream(name, query, who="--as-player", seconds=4):
        """What the client holds after subscribing (`initial`), and the live inserts, by table."""
        name = name.replace("_", "-")
        r = run(DRIVE, "--run", rid, "--query", query, who, "--seconds", seconds, "--save", name, check=False)
        lines = [json.loads(x) for x in (out / f"{name}.jsonl").read_text().splitlines()] if (out / f"{name}.jsonl").exists() else []
        initial, live, error = {}, [], None
        for ev in lines:
            if ev.get("event") == "initial":
                initial = ev.get("tables") or {}
            elif ev.get("event") == "insert":
                live.append(ev["row"])
            if ev.get("status") in ("rejected", "error"):
                error = error or ev.get("error") or ev.get("status")
        return {"exit": r.returncode, "initial": initial, "live": live, "error": error or (r.stderr[-300:] if r.returncode else None)}

    def settle(token, seconds=1.6):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            v.http(f"/v1/database/{db}/call/human_move", [0.0, 0.0, False], token)
            time.sleep(0.25)

    player = st.get("token")
    if not player:
        run(ROOT / ".agents/skills/verify/scripts/verify.py", "player", "--run", rid, "join", "Feed Viewer")
        player = v.load(rid)["token"]
    me = sql("SELECT id FROM my_characters", player)[0]["id"]
    code, body = v.http("/v1/identity", {})
    second = json.loads(body)["token"]
    call("join", ["Feed Second"], second)
    other = sql("SELECT id FROM my_characters", second)[0]["id"]

    call("set_world_law", ["feed_scope_grace_s", "1"])
    call("set_world_law", ["feed_scope_on", "true"])
    end = time.monotonic() + 20
    while time.monotonic() < end and (sql("SELECT * FROM feed_scope", None) or [{}])[0].get("stage") != 2:
        time.sleep(0.3)
    check("the world reaches stage 2", (sql("SELECT * FROM feed_scope", None) or [{}])[0].get("stage") == 2)

    # Stage the scene: a remains far beyond the player's sight, a storage by the second player.
    body = sql("SELECT * FROM my_body", player)[0]
    here = (body["x"], body["y"])
    call("spawn_crowd", [1, True])
    victim = max(c["id"] for c in sql("SELECT id FROM character", owner))
    call("set_behavior", [victim, json.dumps({"wait": 300})])
    far = None
    for dx, dy in ((90, 0), (-90, 0), (0, 90), (0, -90), (70, 70), (-70, -70)):
        try:
            call("place_at", [victim, here[0] + dx, here[1] + dy])
            far = (here[0] + dx, here[1] + dy)
            break
        except RuntimeError:
            continue
    call("kill", [victim, "feed scope client fixture"])
    time.sleep(1)
    remains = [r for r in sql("SELECT * FROM structure_held WHERE kind = 'remains'", owner) if r["owner"] == victim][0]
    call("place_at", [other, here[0] + 40, here[1]])
    call("place_structure", [other, "storage"])
    storage = max((r for r in sql(f"SELECT * FROM structure_held WHERE owner = {other}", owner) if r["kind"] == "storage"), key=lambda r: r["id"])
    settle(player)
    settle(second)
    rk, sk = 1 << 56 | remains["id"], 1 << 56 | storage["id"]

    # The boundary, by SQL and by subscription.
    for table in PRIVATE:
        check(f"SQL: a player cannot select {table}", sql(f"SELECT * FROM {table}", player) is None)
        check(f"SQL: anonymous cannot select {table}", sql(f"SELECT * FROM {table}", None) is None)
    for table in ("structure_held", "thing_seen", "remembered_thing"):
        s = stream(f"feed-ws-{table}", f"SELECT * FROM {table}")
        # Refused by the server (a rejected subscription in the probe's own record), not by the
        # driver before connecting.
        check(f"WebSocket: a player's subscription to {table} is refused", s["exit"] != 0 and bool(s["error"]) and (out / f"feed-ws-{table.replace('_', '-')}.jsonl").exists(), s["error"])
    for table in ("structure", "gate", "resource_node"):
        s = stream(f"feed-ws-legacy-{table}", f"SELECT * FROM {table}")
        check(f"WebSocket: the legacy {table} feed is empty at stage 2", s["exit"] == 0 and not any(s["initial"].values()) and not s["live"], s["initial"])
    mine = stream("feed-ws-my-things-unseen", "SELECT * FROM my_things")
    keys = {r["key"] for t in mine["initial"].values() for r in t}
    check("WebSocket: my_things lacks the unseen remains and the other player's storage", mine["exit"] == 0 and rk not in keys and sk not in keys, sorted(keys))
    keys_sql = {r["key"] for r in sql("SELECT * FROM my_things", player)}
    check("SQL: my_things lacks them too", rk not in keys_sql and sk not in keys_sql)
    truth = stream("feed-ws-owner-truth", "SELECT * FROM thing_seen", who="--as-admin")
    copies = [r for t in truth["initial"].values() for r in t]
    check("owner truth control: the second player's copy of its storage exists, the player has none of the remains",
          any(r["thing"]["key"] == sk for r in copies) and not any(r["thing"]["key"] == rk for r in copies),
          [r["thing"]["key"] for r in copies][:20])
    check("owner truth control: the remains is in structure_held", any(r["id"] == remains["id"] for r in sql("SELECT id FROM structure_held", owner)))

    # In sight: a live insert; then a reconnect's first result.
    proc = subprocess.Popen([sys.executable, str(DRIVE), "--run", rid, "--query", "SELECT * FROM my_things", "--as-player", "--seconds", "8", "--save", "feed-ws-my-things-live"], cwd=ROOT)
    time.sleep(2.5)
    call("place_at", [me, remains["x"] + 2.0, remains["y"]])
    settle(player, 3.0)
    proc.wait(timeout=60)
    live = [json.loads(x) for x in (out / "feed-ws-my-things-live.jsonl").read_text().splitlines()]
    inserted = [ev["row"] for ev in live if ev.get("event") == "insert" and ev.get("table") == "my_things"]
    hit = next((r for r in inserted if r.get("key") == rk), None)
    check("WebSocket: in sight, the remains arrives live in my_things, presence only", hit is not None and hit["kind"] == "remains" and set(hit) >= {"x", "y", "lit", "owner"}, hit)
    again = stream("feed-ws-my-things-reconnect", "SELECT * FROM my_things")
    keys = {r["key"] for t in again["initial"].values() for r in t}
    check("reconnect: a new connection's first result restores the copy", rk in keys, sorted(keys))
    mem = stream("feed-ws-remembered", "SELECT * FROM my_remembered_things")
    keys = {r["key"] for t in mem["initial"].values() for r in t}
    check("reconnect: my_remembered_things holds it", rk in keys, sorted(keys))
    kinds = {r["kind"] for r in sql("SELECT kind FROM map_structure", None)}
    check("map_structure is public and architecture only", bool(kinds) and kinds <= MAP_KINDS, sorted(kinds))
    check("map_resource is public, with no stock", (sql("SELECT * FROM map_resource", None) or [{}])[0].keys() <= {"id", "kind", "x", "y", "chunk"})
    (out / "feed_scope.json").write_text(json.dumps(checks, indent=2) + "\n")
    passed = sum(c["passed"] for c in checks.values())
    print(f"{passed}/{len(checks)} checks passed", flush=True)
    return 0 if passed == len(checks) else 1


if __name__ == "__main__":
    sys.exit(main())
