#!/usr/bin/env python3
"""The trial server's disk plan (docs/TRIAL_DISK.md), approved by the owner on 2026-11-12.

  trial_disk.py list    LIST.json OUT.tsv        the reviewed removal list from `trials.py reclaim --json`
  trial_disk.py archive LIST.json EVIDENCE_DIR   keep each paid and no-model commitlog, compressed, with its module
  trial_disk.py remove  LIST.json EVIDENCE_DIR   remove exactly the listed directories (refuses unless archived)

Reads and writes only the `slop-trials-stdb` volume, through one-off `alpine` containers: read-only
for `archive`, read-write for `remove`, and only while the trial server is stopped. Keeps `live`
(hosted, or written in the 15 minutes before the list) and `unknown` (held) untouched. Every
archive is checked (zstd test, a tar listing equal to the source's files and bytes, sha256) before
anything is removed; any mismatch stops the run.
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

VOLUME = "slop-trials-stdb"
CONTAINER = "slop-trials-stdb"
BASE = "/v/.local/share/spacetime/data/replicas"
ARCHIVE = ("paid", "no-model")
REMOVE = ("paid", "no-model", "fake", "verify")


def sh(*args, input=None, check=True):
    r = subprocess.run(list(args), capture_output=True, input=input)
    if check and r.returncode != 0:
        sys.exit(f"failed: {' '.join(args[:6])}: {r.stderr.decode(errors='replace')[-500:]}")
    return r


def alpine(cmd, rw=False):
    return sh("docker", "run", "--rm", "-v", f"{VOLUME}:/v{'' if rw else ':ro'}", "alpine:latest", "sh", "-c", cmd)


def server_stopped():
    r = sh("docker", "inspect", CONTAINER, "--format", "{{.State.Running}}", check=False)
    return r.stdout.decode().strip() == "false"


def rows(path):
    return json.loads(Path(path).read_text())


def cmd_list(a):
    rs = rows(a.list)
    with open(a.out, "w") as f:
        f.write("replica\tclass\taction\tgb\tclog_gb\tlock\twhat\n")
        for x in sorted(rs, key=lambda x: (x["class"], x["what"], x["replica"])):
            f.write(f"{x['replica']}\t{x['class']}\t{x['action']}\t{x['kb'] / 1048576:.3f}\t{x['clog_kb'] / 1048576:.3f}\t{x['lock'][:19]}\t{x['what']}\n")
    by = {}
    for x in rs:
        by.setdefault(x["class"], [0, 0, 0])
        by[x["class"]][0] += 1
        by[x["class"]][1] += x["kb"]
        by[x["class"]][2] += x["clog_kb"]
    for k, (n, kb, ckb) in sorted(by.items()):
        print(f"{k}: {n} dirs, {kb / 1048576:.1f} GB (commitlogs {ckb / 1048576:.1f} GB)")
    rm = sum(x["kb"] for x in rs if x["class"] in REMOVE)
    ar = sum(x["clog_kb"] for x in rs if x["class"] in ARCHIVE)
    print(f"to remove: {sum(1 for x in rs if x['class'] in REMOVE)} dirs, {rm / 1048576:.1f} GB; "
          f"commitlogs to archive first: {sum(1 for x in rs if x['class'] in ARCHIVE)}, {ar / 1048576:.1f} GB before compression")


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def cmd_archive(a):
    if not server_stopped():
        sys.exit("refusing: stop the trial server first (trials.py down)")
    out = Path(a.evidence)
    out.mkdir(parents=True, exist_ok=True)
    sums = out / "SHA256SUMS"
    manifest = out / "MANIFEST.jsonl"
    done = {json.loads(l)["replica"] for l in manifest.read_text().splitlines()} if manifest.exists() else set()
    modules = {}
    for x in [x for x in rows(a.list) if x["class"] in ARCHIVE]:
        r = x["replica"]
        if r in done:
            continue
        batch, _, inst = (x["what"] or "unattributed/").partition("/")
        d = out / batch
        d.mkdir(exist_ok=True)
        name = f"{inst or 'replica'}-{r}.tar.zst"
        dest = d / name
        parts = f"{r}/clog {r}/module_logs {r}/db.lock"
        # the source's file list with sizes, for the check
        src = alpine(f"cd {BASE} && find {parts} -type f 2>/dev/null | xargs stat -c '%s %n' | sort -k2").stdout.decode().split("\n")
        src = [l for l in src if l.strip()]
        tar = subprocess.Popen(["docker", "run", "--rm", "-v", f"{VOLUME}:/v:ro", "alpine:latest", "tar", "-C", BASE, "-cf", "-", *parts.split()],
                               stdout=subprocess.PIPE)
        z = subprocess.run(["zstd", "-q", "-T8", "-6", "-o", str(dest), "-f"], stdin=tar.stdout)
        tar.stdout.close()
        if tar.wait() != 0 or z.returncode != 0:
            sys.exit(f"STOP: archiving replica {r} failed (tar {tar.returncode}, zstd {z.returncode})")
        # test: zstd integrity, then the tar listing against the source's files and sizes
        if sh("zstd", "-q", "-t", str(dest), check=False).returncode != 0:
            sys.exit(f"STOP: {dest} fails zstd -t")
        listing = subprocess.run(f"zstd -dc '{dest}' | tar -tvf -", shell=True, capture_output=True, text=True)
        got = sorted(f"{l.split()[2]} {l.split()[-1]}" for l in listing.stdout.splitlines() if l and not l.startswith("d"))
        want = sorted(f"{l.split()[0]} {l.split()[1]}" for l in src)
        if listing.returncode != 0 or got != want:
            sys.exit(f"STOP: {dest} does not hold the source's files and sizes ({len(got)} against {len(want)})")
        digest = sha256(dest)
        # its module, once a batch (a commitlog decodes only with the module that wrote it)
        mod = None
        if x.get("module") and x.get("root"):
            wdir = Path(x["root"]).parent / "wasm"
            cands = sorted(wdir.glob(f"{x['module']}.wasm")) + sorted(wdir.glob(f"{x['module']}-wt*.wasm"))
            if cands:
                key = (batch, cands[0].name)
                if key not in modules:
                    mdest = d / cands[0].name
                    mdest.write_bytes(cands[0].read_bytes())
                    modules[key] = sha256(mdest)
                    with open(sums, "a") as f:
                        f.write(f"{modules[key]}  {batch}/{cands[0].name}\n")
                mod = cands[0].name
        with open(sums, "a") as f:
            f.write(f"{digest}  {batch}/{name}\n")
        with open(manifest, "a") as f:
            f.write(json.dumps({"replica": r, "class": x["class"], "batch": batch, "instance": inst, "file": f"{batch}/{name}",
                                "sha256": digest, "bytes": dest.stat().st_size, "source_bytes": sum(int(l.split()[0]) for l in src),
                                "source_files": len(src), "module": mod, "lock": x["lock"]}) + "\n")
        print(f"archived {r} ({x['class']} {x['what']}): {dest.stat().st_size / 1048576:.1f} MB from {sum(int(l.split()[0]) for l in src) / 1048576:.1f} MB; module {mod or 'NOT FOUND'}", flush=True)


def cmd_remove(a):
    if not server_stopped():
        sys.exit("refusing: stop the trial server first (trials.py down)")
    rs = rows(a.list)
    manifest = Path(a.evidence) / "MANIFEST.jsonl"
    archived = {json.loads(l)["replica"] for l in manifest.read_text().splitlines()} if manifest.exists() else set()
    missing = [x["replica"] for x in rs if x["class"] in ARCHIVE and x["replica"] not in archived]
    if missing:
        sys.exit(f"refusing: {len(missing)} commitlogs to keep are not archived and checked (e.g. {missing[:3]})")
    gone = [x["replica"] for x in rs if x["class"] in REMOVE]
    for i in range(0, len(gone), 200):
        chunk = gone[i:i + 200]
        alpine(f"cd {BASE} && for r in {' '.join(chunk)}; do case $r in *[!0-9]*) echo bad $r; exit 1;; esac; rm -rf -- \"$r\"; done", rw=True)
    left = alpine(f"cd {BASE} && ls").stdout.decode().split()
    kept = {x["replica"] for x in rs if x["class"] not in REMOVE}
    if set(gone) & set(left):
        sys.exit(f"STOP: {len(set(gone) & set(left))} listed directories are still there")
    print(f"removed {len(gone)} directories; {len(left)} remain ({len(kept & set(left))} kept as listed, {len(set(left) - kept)} not in the list)")


def main():
    import argparse
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("list"); s.add_argument("list"); s.add_argument("out"); s.set_defaults(f=cmd_list)
    s = sub.add_parser("archive"); s.add_argument("list"); s.add_argument("evidence"); s.set_defaults(f=cmd_archive)
    s = sub.add_parser("remove"); s.add_argument("list"); s.add_argument("evidence"); s.set_defaults(f=cmd_remove)
    a = ap.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
