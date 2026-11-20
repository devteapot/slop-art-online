#!/usr/bin/env python3
"""Watch one world's commitlog, snapshots and memory on a scratch server over a long run.

    python3 living/tools/clog_watch.py --db-prefix verify-lookcost-cl-long- --out DIR
        [--every 30] [--floor-gb 46] [--kill-pid PID]

Waits for a database whose name starts with `--db-prefix`, saves its schema for clog_read.py
(`schema.json`: `spacetime describe --json` and `st_table`), then appends one sample a line to
`samples.jsonl` every `--every` seconds until the database is gone:
- host free disk (GB) where the volume lives;
- the replica's `clog/`: each file's size and whether it is zstd-compressed (2.14.1 compresses the
  sealed segments behind each snapshot in place, same name);
- the replica's `snapshots/`: each entry and its bytes;
- the server process's RSS and peak (VmRSS, VmHWM; the whole service, so the run's own share is
  this less the `baseline` sample taken before the world existed);
- the world's metrics: WASM memory, transactions, rows inserted and deleted per table, snapshot
  and compression counters.
If free disk falls under `--floor-gb`, it pauses the world, writes `ABORTED` and sends SIGINT to
`--kill-pid` (the driver; its cleanup deletes the world, whose files stay on disk), then exits.
"""

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import look_cost as lc  # noqa: E402
import tick_cost as tc  # noqa: E402

DATA = "/home/spacetime/.local/share/spacetime/data/replicas/{}"
VOLUME_HOST = Path.home()

KEEP = ("spacetime_worker_wasm_memory_bytes", "spacetime_num_txns_total", "spacetime_num_rows_inserted_total",
        "spacetime_num_rows_deleted_total", "spacetime_num_bytes_written_total", "spacetime_snapshot_")


def free_gb():
    s = os.statvfs(VOLUME_HOST)
    return round(s.f_bavail * s.f_frsize / 1e9, 2)


def rss():
    pid = tc.server_pid()
    out = {}
    for line in open(f"/proc/{pid}/status"):
        k, _, v = line.partition(":")
        if k in ("VmRSS", "VmHWM"):
            out[k] = int(v.split()[0]) * 1024
    return out


def files(replica):
    """{"clog": [[name, bytes, compressed]], "snapshots": [[name, bytes]]}."""
    r = DATA.format(replica)
    script = (f'cd {r}/clog 2>/dev/null && for f in *; do printf "C %s %s %s\\n" "$f" "$(stat -c %s "$f")" "$(head -c 4 "$f" | od -An -tx1 | tr -d " \\n")"; done; '
              f'cd {r}/snapshots 2>/dev/null && for f in *; do printf "S %s %s\\n" "$f" "$(du -sb "$f" | cut -f1)"; done; true')
    out = subprocess.run(["docker", "exec", lc.CONTAINER, "sh", "-c", script], capture_output=True, text=True).stdout
    res = {"clog": [], "snapshots": []}
    for line in out.splitlines():
        p = line.split()
        if p and p[0] == "C" and len(p) >= 3:
            res["clog"].append([p[1], int(p[2]), len(p) > 3 and p[3] == "28b52ffd"])
        elif p and p[0] == "S" and len(p) == 3:
            res["snapshots"].append([p[1], int(p[2])])
    return res


def metrics(ident):
    m = tc.scrape(ident)
    return {k: v for k, v in m.items() if k.startswith(KEEP)}


def find_db(prefix):
    out = lc.stdb("list", "-s", "local", timeout=60)
    for line in out.splitlines():
        name = line.split("|")[0].strip()
        if name.startswith(prefix):
            return name
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db-prefix", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--every", type=float, default=30.0)
    ap.add_argument("--floor-gb", type=float, default=46.0)
    ap.add_argument("--kill-pid", type=int)
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    log = open(out / "samples.jsonl", "a")

    def write(rec):
        log.write(json.dumps(rec) + "\n")
        log.flush()

    write({"t": time.time(), "kind": "baseline", "free_gb": free_gb(), "rss": rss()})
    db = None
    while not db:
        db = find_db(a.db_prefix)
        if not db:
            time.sleep(5)
    replica = lc.newest_replica()
    token = lc.admin_token()
    ident = json.loads(lc.http(f"/v1/database/{db}")[1])["database_identity"]["__identity__"].removeprefix("0x")
    write({"t": time.time(), "kind": "found", "db": db, "replica": replica, "ident": ident})
    schema_saved = False
    while True:
        t = time.time()
        try:
            code, _ = lc.http(f"/v1/database/{db}")
        except Exception:
            code = None
        if code == 404:
            write({"t": t, "kind": "gone", "files": files(replica), "free_gb": free_gb(), "rss": rss()})
            return
        if not schema_saved:
            try:
                tables = lc.sql(db, "SELECT table_id, table_name FROM st_table", token)
                desc = json.loads(lc.stdb("describe", "-s", "local", "--json", db, timeout=120))
                (out / "schema.json").write_text(json.dumps({"db": db, "describe": desc, "st_table": tables}) + "\n")
                schema_saved = True
            except Exception as e:  # genesis still running, or the CLI busy: next sample
                write({"t": t, "kind": "schema-retry", "error": str(e)[:300]})
        rec = {"t": t, "kind": "sample", "free_gb": free_gb(), "rss": rss(), "files": files(replica)}
        try:
            rec["metrics"] = metrics(ident)
        except Exception as e:
            rec["metrics_error"] = str(e)[:300]
        write(rec)
        if rec["free_gb"] < a.floor_gb:
            try:
                lc.call(db, "set_paused", [True], token)
                paused = lc.sql(db, "SELECT paused FROM world", token)
            except Exception as e:
                paused = str(e)[:300]
            (out / "ABORTED").write_text(f"free {rec['free_gb']} GB < floor {a.floor_gb} GB at {time.strftime('%FT%TZ', time.gmtime(t))}; paused: {paused}\n")
            write({"t": time.time(), "kind": "aborted", "free_gb": rec["free_gb"], "paused": paused})
            if a.kill_pid:
                os.kill(a.kill_pid, signal.SIGINT)
            return
        time.sleep(max(0.0, a.every - (time.time() - t)))


if __name__ == "__main__":
    main()
