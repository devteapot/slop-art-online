#!/usr/bin/env python3
"""Time docs/TRIAL_DISK.md's offline snapshot-and-commitlog prune on a copy of a scratch server.

    python3 living/tools/clog_prune_trial.py --db NAME [--container sg-stdb] [--volume sg-stdb-data]
        [--trial sg-prune] [--trial-port 3345] [--out DIR] [--keep] [--archive PATH.tar.zst] [--in-place]

Run it under `systemd-run --user --scope` (it stops and starts containers). Never against a
reference or trial server: it stops `--container` for the copy.

1. The world is paused and read back as paused; a few counts are read for the check.
2. The server is stopped (SIGINT, until exited): the maintenance window opens.
3. The whole volume is copied to a new volume `<trial>-data` (the cold backup, and the copy pruned).
4. The server is started again and timed until the world answers SQL (its own recovery: the latest
   snapshot and the log after it).
5. On the copy, in the database's replica: the latest snapshot S is kept with the segment covering
   it and every newer segment; older segments (with their offset indexes) and older snapshots go.
6. A second server `<trial>` starts on the copy (port `--port`) and is timed until the world
   answers; the counts, the identity and `paused` must match.
With `--archive PATH`, the stopped server's replica (`clog/`, `snapshots/`, module logs) is first
written to PATH as a tar.zst, tested with `zstd -t` and given a sha256 sidecar (the procedure's
cold backup of the call history). With `--in-place` (the maintenance procedure itself; it requires
`--archive`), steps 3 and 6 are
dropped: the stopped server's own volume is pruned, then the server is started and timed until the
world answers, and the same checks are made. Both containers are started in their own systemd scopes. The trial container and volume are
removed at the end unless `--keep`. Writes `prune-trial.json`.
"""

import argparse
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import world_delete  # noqa: E402

IMAGE = "docker.io/clockworklabs/spacetime:v2.14.1"
DATA = "/home/spacetime/.local/share/spacetime/data"
COUNTS = ("SELECT COUNT(*) AS n FROM body", "SELECT COUNT(*) AS n FROM character", "SELECT COUNT(*) AS n FROM vitals")


def sh(*args, check=True, timeout=7200):
    r = subprocess.run([*map(str, args)], capture_output=True, text=True, timeout=timeout)
    if check and r.returncode:
        raise RuntimeError(f"{' '.join(map(str, args))[:200]}: {r.stderr[-600:]}")
    return r.stdout


def cli(container, *a):
    return subprocess.run(["docker", "exec", "-i", container, "spacetime", *a], capture_output=True, text=True, timeout=600)


def token(container):
    import re
    found = re.findall(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", cli(container, "login", "show", "--token").stdout)
    return found[0] if found else None


def sql(port, db, q, tok):
    req = urllib.request.Request(f"http://127.0.0.1:{port}/v1/database/{db}/sql", data=q.encode(), method="POST")
    req.add_header("Authorization", f"Bearer {tok}")
    with urllib.request.urlopen(req, timeout=600) as r:
        res = json.loads(r.read().decode())[0]
    return res["rows"]


def ident(port, db):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/v1/database/{db}", timeout=60) as r:
        return json.loads(r.read().decode())["database_identity"]["__identity__"]


def counts(port, db, tok):
    return [sql(port, db, q, tok)[0][0] for q in COUNTS] + [sql(port, db, "SELECT paused FROM world", tok)[0][0]]


def until_answers(port, db, container, limit=3600):
    """Seconds until the world answers SQL after a start (the token is read once the CLI answers)."""
    t0 = time.time()
    tok = None
    while time.time() - t0 < limit:
        try:
            tok = tok or token(container)
            if tok:
                sql(port, db, "SELECT paused FROM world", tok)
                return time.time() - t0, tok
        except Exception:
            pass
        time.sleep(1)
    raise RuntimeError(f"{container}: {db} did not answer within {limit} s")


def scoped_start(name):
    sh("systemd-run", "--user", "--scope", f"--unit={name}-{int(time.time())}", "-q", "docker", "start", name)


def stop(name):
    t0 = time.time()
    sh("docker", "kill", "-s", "INT", name)
    sh("docker", "wait", name, check=False, timeout=900)
    return time.time() - t0


def du(volume, path):
    out = sh("docker", "run", "--rm", "--entrypoint", "du", "-v", f"{volume}:/v:ro", IMAGE, "-sb", f"/v{path}")
    return int(out.split()[0])


def archive(volume, rel, dest):
    """The replica's `clog/` and `snapshots/` (and module logs) as one tar.zst (zstd -3; sealed
    segments are already zstd), read from the stopped server's volume; tested with `zstd -t`, with a
    sha256 sidecar. Returns its path, bytes and digest."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "wb") as f:
        tar = subprocess.Popen(["docker", "run", "--rm", "--entrypoint", "tar", "-v", f"{volume}:/v:ro", IMAGE,
                                "-C", f"/v{rel}", "-cf", "-", "clog", "snapshots", "module_logs"], stdout=subprocess.PIPE)
        z = subprocess.run(["zstd", "-3", "-T0", "-q", "-c"], stdin=tar.stdout, stdout=f)
        tar.stdout.close()
        if tar.wait() or z.returncode:
            raise RuntimeError(f"archive {dest}: tar {tar.returncode} zstd {z.returncode}")
    sh("zstd", "-t", "-q", dest)
    digest = sh("sha256sum", dest).split()[0]
    Path(f"{dest}.sha256").write_text(f"{digest}  {dest.name}\n")
    return {"path": str(dest), "bytes": dest.stat().st_size, "sha256": digest}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", required=True)
    ap.add_argument("--container", default="sg-stdb")
    ap.add_argument("--volume", default="sg-stdb-data")
    ap.add_argument("--port", type=int, default=3344, help="the source server's port")
    ap.add_argument("--trial", default="sg-prune")
    ap.add_argument("--trial-port", type=int, default=3345)
    ap.add_argument("--replica", type=int, required=True)
    ap.add_argument("--out", default=".")
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--archive", help="a .tar.zst path: archive the replica's log and snapshots there (verified) while the server is stopped, before the prune")
    ap.add_argument("--in-place", action="store_true", help="prune the stopped server's own volume (its evidence archived first) instead of a copy")
    a = ap.parse_args()
    if a.container in ("sao-living_spacetimedb_1",) or not a.db.startswith("verify-"):
        sys.exit("refusing: only verify-* worlds on a scratch server")
    tv = f"{a.trial}-data"
    res = {"db": a.db, "replica": a.replica, "source": a.container}
    tok = token(a.container)
    state, why = world_delete.pause_confirmed(
        pause=lambda: 200 if cli(a.container, "call", "-s", "local", a.db, "set_paused", "true").returncode == 0 else 0,
        read=lambda: (200, cli(a.container, "sql", "-s", "local", a.db, "SELECT paused FROM world").stdout))
    if state != "paused":
        sys.exit(f"not paused: {why}")
    res["identity"] = ident(a.port, a.db)
    res["counts_before"] = counts(a.port, a.db, tok)
    rep = f"{DATA}/replicas/{a.replica}"
    res["replica_bytes"] = int(sh("docker", "exec", a.container, "du", "-sb", rep).split()[0])
    res["clog_bytes"] = int(sh("docker", "exec", a.container, "du", "-sb", f"{rep}/clog").split()[0])
    res["snapshot_bytes"] = int(sh("docker", "exec", a.container, "du", "-sb", f"{rep}/snapshots").split()[0])

    res["stop_s"] = round(stop(a.container), 2)
    script = f"""set -e
cd /v{rep.removeprefix('/home/spacetime')}
S=$(ls snapshots | sed -n 's/^0*\\([0-9][0-9]*\\)\\.snapshot_dir$/\\1/p' | sort -n | tail -1)
[ -n "$S" ] || {{ echo "no snapshot"; exit 3; }}
C=0
for f in $(ls clog | sed -n 's/^0*\\([0-9][0-9]*\\)\\.stdb\\.log$/\\1/p' | sort -n); do [ "$f" -le "$S" ] && C=$f; done
echo "snapshot $S covering $C"
for f in clog/*.stdb.log; do o=$(basename $f .stdb.log | sed 's/^0*//'); o=${{o:-0}}; if [ "$o" -lt "$C" ]; then echo "rm $f"; rm -f "$f" "clog/$(basename $f .stdb.log).stdb.ofs"; fi; done
for d in snapshots/*.snapshot_dir; do o=$(basename $d .snapshot_dir | sed 's/^0*//'); o=${{o:-0}}; if [ "$o" -lt "$S" ]; then echo "rm $d"; rm -rf "$d"; fi; done
"""
    if a.archive:
        # The cold backup of the call history, off the volume, verified before anything is removed.
        t0 = time.time()
        res["archive"] = archive(a.volume, rep.removeprefix("/home/spacetime"), Path(a.archive))
        res["archive_s"] = round(time.time() - t0, 2)
    if a.in_place:
        if not a.archive:
            sys.exit("--in-place needs --archive (the log is kept off the volume before it is pruned)")
        # The maintenance window itself: prune the stopped server's own volume, start it, recover.
        res["mode"] = "in place"
        t0 = time.time()
        res["prune_log"] = sh("docker", "run", "--rm", "--entrypoint", "sh", "-v", f"{a.volume}:/v", IMAGE, "-c", script).splitlines()
        res["prune_s"] = round(time.time() - t0, 2)
        res["pruned_replica_bytes"] = du(a.volume, rep.removeprefix("/home/spacetime"))
        scoped_start(a.container)
        res["recovery_s"], tok = until_answers(a.port, a.db, a.container)
        res["recovery_s"] = round(res["recovery_s"], 2)
        res["identity_after"] = ident(a.port, a.db)
        res["counts_after"] = counts(a.port, a.db, tok)
        res["match"] = res["identity_after"] == res["identity"] and res["counts_after"] == res["counts_before"]
    else:
        res["mode"] = "on a copy"
        t0 = time.time()
        sh("docker", "volume", "create", tv)
        sh("docker", "run", "--rm", "--entrypoint", "cp", "-v", f"{a.volume}:/src:ro", "-v", f"{tv}:/dst", IMAGE, "-a", "/src/.", "/dst/")
        res["copy_s"] = round(time.time() - t0, 2)
        res["copy_bytes"] = du(tv, "")
        scoped_start(a.container)
        res["source_recovery_s"], tok = until_answers(a.port, a.db, a.container)
        res["source_recovery_s"] = round(res["source_recovery_s"], 2)
        res["counts_source_after"] = counts(a.port, a.db, tok)
        t0 = time.time()
        res["prune_log"] = sh("docker", "run", "--rm", "--entrypoint", "sh", "-v", f"{tv}:/v", IMAGE, "-c", script).splitlines()
        res["prune_s"] = round(time.time() - t0, 2)
        res["pruned_replica_bytes"] = du(tv, rep.removeprefix("/home/spacetime"))
        sh("docker", "create", "--name", a.trial, "-p", f"127.0.0.1:{a.trial_port}:3000", "-v", f"{tv}:/home/spacetime", IMAGE, "start")
        scoped_start(a.trial)
        res["trial_recovery_s"], ttok = until_answers(a.trial_port, a.db, a.trial)
        res["trial_recovery_s"] = round(res["trial_recovery_s"], 2)
        res["trial_identity"] = ident(a.trial_port, a.db)
        res["counts_trial"] = counts(a.trial_port, a.db, ttok)
        res["match"] = res["trial_identity"] == res["identity"] and res["counts_trial"] == res["counts_before"]
        stop(a.trial)
        if not a.keep:
            sh("docker", "rm", a.trial)
            sh("docker", "volume", "rm", tv)
            res["trial_removed"] = True
    Path(a.out, "prune-trial.json").write_text(json.dumps(res, indent=1) + "\n")
    print(json.dumps(res, indent=1))
    sys.exit(0 if res["match"] else 1)

if __name__ == "__main__":
    main()
