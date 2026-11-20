#!/usr/bin/env python3
"""A made world's tables, hashed, so two builds' genesis can be compared (docs/STAGED_GENESIS.md §5).

    python3 living/tools/genesis_hash.py --out FILE WASM          # publish WASM fresh, wait, hash, delete
    python3 living/tools/genesis_hash.py --compare A.json B.json  # tables whose content differs

Publishes the module (built with LIVING_NO_TICK=1, so the made world stays still) on the worker's
own server (`LIVING_STDB_CONTAINER`, `LIVING_STDB_URL`), waits until it is made (genesis_wait.py),
reads every table of the authority's source as the owner and records per table its row count and
two hashes of its sorted rows:

- `full`: every column, times (integers within about 3 years of `world.epoch_ms`) taken relative
  to it;
- `content`: the same without id-like columns (`id`, `*_id` and the columns that hold another row's
  id). Auto-increment ids are handed out in an order that differs between publishes of the same
  module (the same rows, other numbers: insertion order from hash-map iteration at genesis), so
  `content` is what two creations of one seed share.

The clock, genesis, timer and connection tables are left out (the run's own, not genesis). The
database is deleted after (world_delete.py).
"""
import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import look_cost as lc  # noqa: E402
import genesis_wait  # noqa: E402

SKIP = {"clock", "genesis", "genesis_timer", "tick_timer", "slow_timer", "connection"}
IDLIKE = {"id", "owner", "holder", "target", "body", "observer", "subject", "of", "structure", "lot", "chunk", "actor", "other", "viewer", "community", "settlement", "parent", "mother", "father", "partner", "person", "character"}


def tables():
    src = "\n".join(p.read_text() for p in (ROOT / "living/authority/src").glob("*.rs"))
    return sorted(set(re.findall(r"spacetimedb::table\(\s*accessor\s*=\s*(\w+)", src)) - SKIP)


def norm(v, epoch):
    if isinstance(v, int) and abs(v - epoch) < 10**11:
        return ["rel", v - epoch]
    if isinstance(v, list):
        return [norm(x, epoch) for x in v]
    return v


def digest(lines):
    return hashlib.sha256("\n".join(sorted(lines)).encode()).hexdigest()[:16]


def hash_world(wasm, out):
    db = f"verify-lookcost-hash-{Path(wasm).stem.replace('_', '-')}-{time.strftime('%H%M%S')}"[:60]
    p = subprocess.run(["docker", "exec", "-i", lc.CONTAINER, "spacetime", "publish", "-s", "local", "-b", f"/wasm/{wasm}", db, "--delete-data", "-y"], capture_output=True, text=True, timeout=1800)
    if p.returncode:
        sys.exit(f"publish failed: {(p.stderr or p.stdout)[-300:]}")
    try:
        token = lc.admin_token()
        genesis_wait.wait_ready(lc.URL, db, token)
        epoch = lc.sql(db, "SELECT epoch_ms FROM world", token)[0]["epoch_ms"]
        ticks = lc.sql(db, "SELECT tick FROM clock", token)[0]["tick"]
        res = {"wasm": wasm, "ticks_at_read": ticks, "tables": {}}
        for t in tables():
            code, body = lc.http(f"/v1/database/{db}/sql", f"SELECT * FROM {t}", token, raw=True)
            if code != 200:
                res["tables"][t] = None
                continue
            r = json.loads(body)[0]
            names = [c["name"]["some"] if isinstance(c.get("name"), dict) else c.get("name") for c in r["schema"]["elements"]]
            rows = [[norm(v, epoch) for v in row] for row in r["rows"]]
            keep = [i for i, n in enumerate(names) if not (n in IDLIKE or n.endswith("_id"))]
            res["tables"][t] = {"rows": len(rows), "full": digest(json.dumps(x) for x in rows), "content": digest(json.dumps([x[i] for i in keep]) for x in rows)}
        Path(out).write_text(json.dumps(res, indent=1) + "\n")
        print(json.dumps({"wasm": wasm, "ticks_at_read": ticks, "tables": len(res["tables"]), "rows": sum(v["rows"] for v in res["tables"].values() if v)}))
    finally:
        lc.delete_world(db)


def compare(a, b):
    ta, tb = json.load(open(a))["tables"], json.load(open(b))["tables"]
    out = {"rows_differ": [], "content_differs": [], "ids_only": []}
    for t in sorted(set(ta) | set(tb)):
        x, y = ta.get(t), tb.get(t)
        if x == y:
            continue
        if not x or not y or x["rows"] != y["rows"]:
            out["rows_differ"].append(t)
        elif x["content"] != y["content"]:
            out["content_differs"].append(t)
        else:
            out["ids_only"].append(t)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out")
    ap.add_argument("--compare", nargs=2)
    ap.add_argument("wasm", nargs="?")
    a = ap.parse_args()
    if a.compare:
        print(json.dumps(compare(*a.compare)))
    else:
        hash_world(a.wasm, a.out)
