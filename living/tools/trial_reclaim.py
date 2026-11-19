#!/usr/bin/env python3
"""Inventory or reclaim retired replicas on the pinned Spark trial server."""
import argparse
import collections
import contextlib
import datetime
import fcntl
import hashlib
import json
import re
import subprocess
import tarfile
import tempfile
import time
from fnmatch import fnmatchcase
from pathlib import Path

import trial_archive
import world_guard

HOME = Path.home()
QUEUE = HOME / "slop-mq"
EVIDENCE = HOME / "slop-evidence"
SERVER = "slop-trials-stdb"
IMAGE = "clockworklabs/spacetime:v2.14.1"
URL = "http://127.0.0.1:3320"
DATA = "/home/spacetime/.local/share/spacetime/data"
OFFLINE = "/v/.local/share/spacetime/data"
HAMLETS = "verify-trial-bi1-hamlet-*"
ROOT = Path(__file__).resolve().parent
REPLICA = re.compile(r"[1-9][0-9]*")
SNAPSHOT = re.compile(r"replicas/([1-9][0-9]*)/snapshots/[0-9]+\.snapshot_dir/[0-9]+\.snapshot_bsatn")
ARCHIVE = re.compile(r"(.+)-([0-9a-f]{12})-([1-9][0-9]*)-[0-9]{8}T[0-9]+Z\.tar\.zst")
PROCESSES = {"drain.sh", "merge2.sh", "scene_gate.py", "trials.py", "battle_diag.py", "verify.py"}
SCRATCH = ("verify-gate-", "verify-core-", "verify-player-", "verify-client-", "verify-ui-", "verify-generation-")
LOG = QUEUE / "reclaim.log"


def command(*args, **kwargs):
    return subprocess.check_output(args, **kwargs)


def mount(script, *, writable=False, args=()):
    # --mount and a preflight volume inspect keep the target fixed.
    flags = "" if writable else ",readonly"
    return ("docker", "run", "--rm", "--pull", "never", "--network", "none", "--user", "0",
            "--mount", f"type=volume,src={SERVER},dst=/v{flags}", "--entrypoint", "sh",
            IMAGE, "-eu", "-c", script, "trial-reclaim", *args)


def preflight():
    info = json.loads(command("docker", "inspect", "--type", "container", SERVER))[0]
    if info["Config"]["Image"] != IMAGE or not any(
        m["Type"] == "volume" and m["Name"] == SERVER and m["Destination"] == "/home/spacetime"
        for m in info["Mounts"]
    ):
        raise RuntimeError("unexpected trial container image or volume")
    command("docker", "volume", "inspect", SERVER)
    ports = info["NetworkSettings"]["Ports"].get("3000/tcp") or []
    if not any(p["HostPort"] == "3320" and p["HostIp"] in {"127.0.0.1", "0.0.0.0"} for p in ports):
        raise RuntimeError("trial container is not serving the configured localhost port")
    if not info["State"]["Running"]:
        raise RuntimeError("trial server must be running at inventory time")
    version = command("docker", "exec", SERVER, "/opt/spacetime/spacetimedb-standalone", "--version")
    if b"tool version 2.14.1;" not in version:
        raise RuntimeError("trial server binary is outside the supported version")


def collect_metadata(reader, *, running, include_snapshots=True):
    with tempfile.TemporaryDirectory(prefix="trial-reclaim-") as tmp:
        path = Path(tmp)
        # Only copy the sled trees and snapshot manifests. Snapshot pages and blobs stay on disk.
        script = 'cd "$1"; find control-db -type f -print0'
        if include_snapshots:
            script += '; find replicas -maxdepth 4 -type f -name "*.snapshot_bsatn" -print0'
        tar_script = 'cd "$1"; tar --null --no-recursion -cf - -T -'
        if running:
            invoke = lambda s: ("docker", "exec", "-i", SERVER, "sh", "-eu", "-c", s, "trial-reclaim", DATA)
        else:
            invoke = lambda s: mount(s, args=(OFFLINE,))
        names = command(*invoke(script), timeout=120)
        with tempfile.TemporaryFile() as copied:
            subprocess.run(invoke(tar_script), input=names, stdout=copied, check=True, timeout=180)
            copied.seek(0)
            snapshots = []
            with tarfile.open(fileobj=copied) as archive:
                for entry in archive:
                    match = SNAPSHOT.fullmatch(entry.name)
                    if not entry.isfile() or not (match or re.fullmatch(r"control-db(?:/blobs)?/[a-zA-Z0-9.]+", entry.name)):
                        raise RuntimeError(f"unexpected metadata archive entry: {entry.name}")
                    target = path / entry.name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(archive.extractfile(entry).read())
                    if match:
                        snapshots.append(str(target))
        result = json.loads(command(str(reader), str(path / "control-db"),
                                    input="".join(f"{s}\n" for s in snapshots), text=True, timeout=120))
        return result["control"], {str(Path(p).relative_to(path)): row for p, row in result["snapshots"].items()}


def sizes(*, running):
    script = 'cd "$1"; du -B1 --max-depth=1 -- replicas'
    args = ("docker", "exec", SERVER, "sh", "-eu", "-c", script, "trial-reclaim", DATA) if running else mount(script, args=(OFFLINE,))
    result = {}
    for line in command(*args, text=True, timeout=180).splitlines():
        size, _, path = line.partition("\t")
        if path.startswith("replicas/"):
            result[path.removeprefix("replicas/")] = int(size)
    return result


def evidence_index(directory):
    historical = collections.defaultdict(list)
    archives = collections.defaultdict(list)
    manifest = directory / "commitlogs-20261112/MANIFEST.jsonl"
    if manifest.is_file():
        for line in manifest.read_text().splitlines():
            row = json.loads(line)
            name = f"verify-trial-{row['batch']}-{row['instance']}"
            path = manifest.parent / row["file"]
            if path.resolve().is_relative_to(manifest.parent.resolve()):
                historical[str(row["replica"])].append((name, row["class"], path, row["sha256"]))
    for path in directory.glob("*.tar.zst"):
        if match := ARCHIVE.fullmatch(path.name):
            if path.resolve().is_relative_to(directory.resolve()):
                archives[match[3]].append((match[1], match[2], path))
    return historical, archives


def check_archive(path, supplied, expected, replica):
    try:
        if supplied is None:
            checksum = path.with_suffix(".zst.sha256").read_text().split()
            if len(checksum) != 2 or checksum[1] != path.name:
                return False
            supplied = checksum[0]
        with path.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != supplied:
                return False
        if subprocess.run(["zstd", "-qt", path], capture_output=True).returncode:
            return False
        found = {}
        with subprocess.Popen(["zstd", "-dc", path], stdout=subprocess.PIPE) as process:
            with process.stdout:
                with tarfile.open(fileobj=process.stdout, mode="r|") as archive:
                    for entry in archive:
                        name = entry.name.removeprefix(f"{replica}/")
                        if entry.isdir() or not name.startswith("clog/"):
                            continue
                        if not entry.isfile() or name in found:
                            return False
                        found[name] = hashlib.file_digest(archive.extractfile(entry), "sha256").hexdigest()
                # Drain trailing tar padding before waiting on the decompressor.
                while process.stdout.read(65536):
                    pass
            return process.wait() == 0 and found == expected
    except (OSError, tarfile.TarError, ValueError):
        return False


def log_hashes(replica, *, running):
    script = 'cd "$1/replicas/$2"; test -d clog; find clog -type f -exec sha256sum {} +'
    args = ("docker", "exec", SERVER, "sh", "-eu", "-c", script, "trial-reclaim", DATA, replica) if running else mount(script, args=(OFFLINE, replica))
    rows = command(*args, text=True, timeout=180).splitlines()
    hashes = {path: sha for sha, path in (row.split("  ", 1) for row in rows)}
    if not any(name.endswith(".stdb.log") for name in hashes):
        raise ValueError("no commitlog segments to verify")
    return hashes


def plan(control, snapshots, disk_sizes, index, keep, verified):
    historical, archives = index
    known_live = {v["identity"] for v in control["databases"].values()}
    by_replica = collections.defaultdict(list)
    for path, metadata in snapshots.items():
        if match := SNAPSHOT.fullmatch(path):
            by_replica[match[1]].append(metadata)
    rows = []
    for replica, size in sorted(disk_sizes.items()):
        row = dict(replica=replica, bytes=size, classification="unknown", identity=None, names=[],
                   action="keep", reason="replica has no unambiguous hash-verified snapshot mapping")
        rows.append(row)
        if replica in control["replicas"]:
            db = control["databases"].get(str(control["replicas"][replica]), {})
            row.update(classification="live", identity=db.get("identity"), names=db.get("names", []),
                       reason="replica is registered in the control database")
            continue
        manifests = by_replica[replica]
        if not REPLICA.fullmatch(replica) or not manifests or any(
            not m or str(m["replica"]) != replica for m in manifests
        ):
            continue
        identities = {m["identity"] for m in manifests}
        if len(identities) != 1:
            continue
        identity = identities.pop()
        names = control["aliases"].get(identity, [])
        row.update(identity=identity, names=names)
        if identity in known_live:
            row.update(classification="live", reason="snapshot belongs to a live database")
            continue
        if not names:
            row["reason"] = "database name unavailable for keep-list check"
            continue
        if any(fnmatchcase(name, pattern) for name in names for pattern in keep):
            row["reason"] = "database matches explicit keep-list"
            continue
        records = [(kind, path, sha) for name, kind, path, sha in historical[replica] if name in names]
        kinds = {kind for kind, _, _ in records if kind in {"paid", "no-model", "fake", "verify"}}
        if len(kinds) == 1:
            row["classification"] = kinds.pop()
        elif not kinds and all(name.startswith(SCRATCH) for name in names):
            row["classification"] = "verify"
        candidates = [(path, sha) for _, path, sha in records]
        labels = {re.sub(r"[^a-zA-Z0-9_-]", "_", name) for name in names}
        candidates.extend((path, None) for label, prefix, path in archives[replica]
                          if label in labels and identity.startswith(prefix))
        archive = verified(replica, candidates) if candidates else None
        if archive:
            row.update(action="delete", reason="database absent from control tables and commitlog archive verified",
                       archive=str(archive))
        elif row["classification"] in {"no-model", "fake", "verify"}:
            row.update(action="delete-after-archive", reason="database absent from control tables; archive required before removal")
        else:
            row["reason"] = "needs archive"
    return rows


def blockers():
    reasons = []
    if (QUEUE / "queue.txt").read_text().strip() and not (QUEUE / "HOLD").exists():
        reasons.append("merge queue is nonempty and HOLD is absent")
    active = set()
    for process in Path("/proc").iterdir():
        if not process.name.isdecimal():
            continue
        try:
            argv = (process / "cmdline").read_bytes().split(b"\0")
        except (ProcessLookupError, FileNotFoundError, PermissionError):
            continue
        executable = Path(argv[0].decode(errors="replace")).name
        if executable in PROCESSES:
            active.add(executable)
        elif executable.startswith(("python", "bash", "sh")):
            script = next((a for a in argv[1:] if a and not a.startswith(b"-")), b"")
            name = Path(script.decode(errors="replace")).name
            if name in PROCESSES:
                active.add(name)
    if active:
        reasons.append("active processes: " + ", ".join(sorted(active)))
    return reasons


def quiet_worlds(control):
    reasons = []
    for db in control["databases"].values():
        status, row = world_guard.world(f"{URL}/v1/database/{db['identity']}", None)
        if status != 200 or not row or row[1] is not True:
            reasons.append("pause not confirmed for " + (", ".join(db["names"]) or db["identity"]))
    return reasons


@contextlib.contextmanager
def maintenance_locks():
    reasons = []
    with contextlib.ExitStack() as stack:
        for name in ("battle.lock", "drain.lock", "lock", "trial-activity.lock"):
            lock = stack.enter_context((QUEUE / name).open("a"))
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                reasons.append(f"{name} is held")
        yield reasons


def probe_locks():
    with maintenance_locks() as reasons:
        return reasons


def metadata_reader():
    target = HOME / ".cache/slop-trial-reclaim"
    subprocess.run(["cargo", "build", "--quiet", "--locked", "--manifest-path",
                    ROOT / "reclaim_metadata/Cargo.toml", "--target-dir", target], check=True)
    return target / "debug/trial-reclaim-metadata"


def verify_existing(replica, candidates, *, running):
    try:
        expected = log_hashes(replica, running=running)
    except (subprocess.SubprocessError, ValueError):
        return None
    return next((path for path, sha in candidates if check_archive(path, sha, expected, replica)), None)


def write_record(record, output):
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_suffix(".json.tmp")
    totals = collections.defaultdict(lambda: {"replicas": 0, "bytes": 0})
    classifications = collections.defaultdict(lambda: {"replicas": 0, "bytes": 0})
    for row in record["replicas"]:
        for tally in (totals[row["action"]], classifications[row["classification"]]):
            tally["replicas"] += 1
            tally["bytes"] += row["bytes"]
    record["totals"] = dict(totals)
    record["classifications"] = dict(classifications)
    tmp.write_text(json.dumps(record, indent=2) + "\n")
    tmp.replace(output)
    lines = [f"{record['time']} {'dry run' if record['dry_run'] else 'reclaim'} {SERVER}"]
    lines.extend(f"BLOCKED {reason}" for reason in record["blockers"])
    for label, tally in sorted(totals.items()):
        lines.append(f"{label}  {tally['replicas']} directories  {tally['bytes'] / 1e9:.3f} GB")
    for label, tally in sorted(classifications.items()):
        lines.append(f"class {label}  {tally['replicas']} directories  {tally['bytes'] / 1e9:.3f} GB")
    lines.append(f"removed {len(record['removed'])} directories, {sum(r['bytes'] for r in record['removed']) / 1e9:.3f} GB")
    summary = lines + ["", "Replica\tBytes\tClass\tAction\tReason\tNames"]
    summary.extend(f"{r['replica']}\t{r['bytes']}\t{r['classification']}\t{r['action']}\t{r['reason']}\t{','.join(r['names'])}"
                   for r in record["replicas"])
    output.with_suffix(".txt").write_text("\n".join(summary) + "\n")
    with LOG.open("a") as log:
        print(*lines, f"JSON {output}", sep="\n", file=log)
        for row in record["removed"]:
            print(f"removed {row['replica']} {row['bytes']} bytes: {row['reason']}; {row['archive']}", file=log)
    print(*lines, f"JSON {output}", f"Summary {output.with_suffix('.txt')}", sep="\n")


def reclaim(reader, control, candidates, record, output):
    # Validate the archive before stopping to keep downtime short. The offline pass rechecks
    # authoritative identity and the archived bytes before granting a write mount.
    if not candidates:
        return
    if fresh := blockers() + quiet_worlds(control):
        record["blockers"].extend(fresh)
        return
    for row in candidates:
        if row["action"] == "delete-after-archive":
            archive = trial_archive.archive(SERVER, row["replica"], row["names"][0], row["identity"], EVIDENCE)
            row.update(archive=str(archive), action="delete",
                       reason="database absent from control tables and commitlog archive created")
    current, _ = collect_metadata(reader, running=True, include_snapshots=False)
    if current != control:
        record["blockers"].append("live control metadata changed during the inventory")
        return
    if fresh := blockers() + quiet_worlds(current):
        record["blockers"].extend(fresh)
        return
    # Run the signal against PID 1 inside the verified container. Never force-stop it.
    try:
        subprocess.run(["docker", "exec", "--user", "0", SERVER, "kill", "-INT", "1"], check=True)
        exit_code = command("docker", "wait", SERVER, text=True, timeout=60).strip()
        if exit_code != "0":
            raise RuntimeError(f"trial server did not exit cleanly (exit {exit_code})")
        offline, snapshots = collect_metadata(reader, running=False)
        if offline != control:
            raise RuntimeError("control metadata changed since the live inventory")
        offline_rows = plan(offline, snapshots, {r["replica"]: r["bytes"] for r in candidates},
                            (collections.defaultdict(list), collections.defaultdict(list)),
                            record["keep_list"], lambda *_: None)
        for row, latest in zip(candidates, offline_rows, strict=True):
            if (latest["replica"], latest["identity"], latest["names"]) != (row["replica"], row["identity"], row["names"]):
                continue
            if latest["classification"] == "live" or latest["reason"] in {
                "database matches explicit keep-list", "database name unavailable for keep-list check",
            }:
                continue
            archive = Path(row["archive"])
            # The historical manifest supplies its own checksum.
            historical, _ = evidence_index(EVIDENCE)
            sha = next((sha for _, _, path, sha in historical[row["replica"]] if path == archive), None)
            if not verify_existing(row["replica"], [(archive, sha)], running=False):
                row.update(action="keep", reason="needs archive: offline commitlog verification failed")
                continue
            if command("docker", "inspect", "--format", "{{.State.Running}}", SERVER).strip() != b"false":
                raise RuntimeError("trial server started during its maintenance window")
            script = 'case "$2" in ""|*[!0-9]*) exit 2;; esac; cd "$1/replicas"; test -d "$2"; test ! -L "$2"; rm -rf --one-file-system -- "$2"'
            subprocess.run(mount(script, writable=True, args=(OFFLINE, row["replica"])), check=True, timeout=180)
            record["removed"].append(dict(row))
            output.with_suffix(".json.partial").write_text(json.dumps(record, indent=2) + "\n")
    finally:
        if command("docker", "inspect", "--format", "{{.State.Running}}", SERVER).strip() == b"false":
            restart(control)


def restart(control):
    subprocess.run(["docker", "start", SERVER], check=True)
    subprocess.run(["docker", "exec", "-u", "1000", SERVER,
                    "prlimit", "--pid", "1", "--nofile=65536:524288"], check=True)
    for _ in range(60):
        if world_guard.request(URL + "/v1/ping", None)[0] == 200:
            break
        time.sleep(1)
    else:
        raise RuntimeError("trial server did not become ready after restart")
    if after := quiet_worlds(control):
        raise RuntimeError("; ".join(after))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="read-only inventory, even if a quiet-window gate is blocked")
    mode.add_argument("--apply", action="store_true", help="maintenance mode, for use after GC approval")
    parser.add_argument("--if-over-gb", type=float)
    parser.add_argument("--keep", action="append", default=[], metavar="NAME_OR_GLOB")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    now = datetime.datetime.now(datetime.timezone.utc)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    mode = "dryrun" if args.dry_run else "apply"
    output = args.output or EVIDENCE / f"reclaim-{mode}-{stamp}.json"
    if args.if_over_gb is not None and float(command(str(ROOT / "trial_volume_size.sh"))) <= args.if_over_gb:
        print(f"Volume is at or below {args.if_over_gb:g} GB")
        return 0
    record = dict(time=now.isoformat(), dry_run=args.dry_run, keep_list=[HAMLETS, *args.keep],
                  blockers=[], replicas=[], removed=[])
    locks = maintenance_locks() if args.apply else contextlib.nullcontext(probe_locks())
    with locks as reasons:
        record["blockers"].extend(reasons + blockers())
        try:
            if record["blockers"] and args.apply:
                return 1
            preflight()
            reader = metadata_reader()
            control, snapshots = collect_metadata(reader, running=True)
            record["live_databases"] = control["databases"]
            record["live_replicas"] = control["replicas"]
            record["blockers"].extend(quiet_worlds(control))
            if record["blockers"] and args.apply:
                return 1
            record["replicas"] = plan(control, snapshots, sizes(running=True), evidence_index(EVIDENCE),
                                      record["keep_list"],
                                      lambda replica, candidates: verify_existing(replica, candidates, running=True))
            latest, _ = collect_metadata(reader, running=True, include_snapshots=False)
            if latest != control:
                record["blockers"].append("control metadata changed during inventory; rerun before using this plan")
            if args.apply and not record["blockers"]:
                candidates = [r for r in record["replicas"] if r["action"].startswith("delete")]
                reclaim(reader, control, candidates, record, output)
                return int(bool(record["blockers"]))
            return int(args.apply and bool(record["blockers"]))
        except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as error:
            record["blockers"].append(str(error))
            return 1
        finally:
            write_record(record, output)
            output.with_suffix(".json.partial").unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
