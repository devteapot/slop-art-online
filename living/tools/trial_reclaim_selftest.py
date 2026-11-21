#!/usr/bin/env python3
"""Exercise reclaim decisions and exact archive matching on a fake replica tree."""
import collections
import hashlib
import io
import os
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path

from unittest.mock import patch

import trial_reclaim
from trial_reclaim import HAMLETS, OFFLINE, blockers, check_archive, check_report_paths, collect_metadata, plan, replica_removal_command, restrict_to_review


class ReclaimTests(unittest.TestCase):
    def test_fake_replica_inventory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            identities = {str(i): f"{i:064x}" for i in range(1, 10)}
            database_names = {
                "1": "verify-trial-bi1-hamlet-one", "2": "verify-minds-reset",
                "3": "verify-core-old", "4": "verify-trial-paid-paid-r1",
                "5": "verify-minds-other", "6": "verify-core-protect", "7": "verify-minds-unknown",
                "8": "verify-core-wrong-replica", "9": "verify-trial-fake-fake-r1",
            }
            control = {"databases": {"33": {"identity": identities["1"], "names": [database_names["1"]]},
                                     "34": {"identity": identities["2"], "names": [database_names["2"]]}},
                       "replicas": {"1": 33}, "aliases": {
                           identity: [database_names[replica]] for replica, identity in identities.items()}}
            disk_sizes, snapshots = {}, {}
            for replica in identities:
                replica_dir = root / "replicas" / replica
                replica_dir.mkdir(parents=True)
                log = replica_dir / "log"
                log.write_bytes(bytes(int(replica)))
                disk_sizes[replica] = log.stat().st_size
                if replica != "7":
                    name = f"replicas/{replica}/snapshots/01.snapshot_dir/01.snapshot_bsatn"
                    snapshots[name] = {"replica": 99 if replica == "8" else int(replica), "identity": identities[replica]}
            records = collections.defaultdict(list, {
                "4": [(database_names["4"], "paid", root / "missing", "checksum")],
                "9": [(database_names["9"], "fake", root / "missing", "checksum")],
            })
            archives = collections.defaultdict(list, {
                "5": [(database_names["5"], identities["5"][:12], root / "valid.tar.zst")],
            })
            rows = {row["replica"]: row for row in plan(
                control, snapshots, disk_sizes, (records, archives), [HAMLETS, "verify-core-protect"],
                lambda replica, candidates: candidates[0][0] if replica == "5" else None)}
            self.assertEqual([rows[str(i)]["action"] for i in range(1, 10)],
                             ["keep", "keep", "delete-after-archive", "keep", "delete", "keep", "keep", "keep",
                              "delete-after-archive"])
            self.assertEqual(rows["4"]["reason"], "needs archive")
            self.assertEqual(rows["2"]["classification"], "live")
            self.assertEqual(rows["6"]["reason"], "database matches explicit keep-list")
            self.assertIsNone(rows["8"]["identity"])
            self.assertEqual(sum(r["bytes"] for r in rows.values()), 45)

    def test_review_holds_paid_and_new_replicas(self):
        evidence = Path("/evidence")
        archive = str(evidence / "checked.tar.zst")
        def replica(number):
            return dict(replica=str(number), identity=f"{number:064x}", names=[f"verify-core-{number}"],
                        action="delete", classification="verify", reason="verified")
        rows = [replica(i) for i in range(1, 6)]
        rows[4].update(classification="live", action="keep")
        approved = [dict(rows[0], archive=archive), dict(rows[1], action="keep", reason="paid, archived"),
                    dict(rows[2], identity="changed"), dict(rows[4])]
        restrict_to_review(rows, {"dry_run": True, "replicas": approved}, evidence,
                           lambda replica, candidates: replica == "1")
        self.assertEqual([row["action"] for row in rows], ["delete", "keep", "keep", "keep", "keep"])
        self.assertEqual(rows[1]["reason"], "paid, archived")
        self.assertEqual(rows[4]["classification"], "live")

    def test_offline_copy_feeds_tar_list_and_rejects_empty_copy(self):
        files = b"control-db/conf\0control-db/db\0"
        def copy_fixture(args, *, input, stdout, **kwargs):
            self.assertIn("-i", args)
            self.assertIn(",readonly", next(arg for arg in args if arg.startswith("type=volume")))
            self.assertEqual(input, files)
            with tarfile.open(fileobj=stdout, mode="w") as archive:
                for name in transfer:
                    entry = tarfile.TarInfo(name)
                    entry.size = 1
                    archive.addfile(entry, io.BytesIO(b"x"))

        with patch("trial_reclaim.command", side_effect=[
                files, '{"control": {}, "snapshots": {}}']) as command, patch(
                "trial_reclaim.subprocess.run", side_effect=copy_fixture):
            transfer = ["control-db/conf", "control-db/db"]
            self.assertEqual(collect_metadata("reader", running=False), ({}, {}))
            self.assertEqual(command.call_args.args[0], "reader")

        with patch("trial_reclaim.command", return_value=files) as command, patch(
                "trial_reclaim.subprocess.run", side_effect=copy_fixture):
            transfer = []
            with self.assertRaisesRegex(RuntimeError, "metadata copy is missing control-db/conf"):
                collect_metadata("reader", running=False)
            self.assertEqual(command.call_count, 1)  # Never start sled against an empty directory.

    def test_evidence_is_never_a_removal_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence = root / "slop-evidence"
            archive = evidence / "reclaim-archives-20261119"
            archive.mkdir(parents=True)
            alias = root / "evidence-alias"
            alias.symlink_to(evidence, target_is_directory=True)
            with patch("trial_reclaim.EVIDENCE", evidence):
                for target in (evidence, archive / "123", alias / "123"):
                    with self.subTest(target=target), self.assertRaisesRegex(ValueError, "slop-evidence"):
                        replica_removal_command(target)
                with self.assertRaisesRegex(ValueError, "protected evidence"):
                    check_report_paths(archive / "report.json")
                check_report_paths(evidence / "reclaim-report.json")
                with self.assertRaisesRegex(ValueError, "numeric child"):
                    replica_removal_command(Path(OFFLINE) / "replicas" / ".." / "123")
                self.assertEqual(replica_removal_command(Path(OFFLINE) / "replicas" / "123")[-1],
                                 f"{OFFLINE}/replicas/123")

    def test_archive_matches_exact_commitlog(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log = root / "clog/00000000000000000000.stdb.log"
            log.parent.mkdir()
            log.write_bytes(b"fake call history")
            tar = root / "calls.tar"
            with tarfile.open(tar, "w") as stream:
                stream.add(log.parent, arcname="clog")
            archive = root / "calls.tar.zst"
            subprocess.run(["zstd", "-q", tar, "-o", archive], check=True)
            checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
            archive.with_suffix(".zst.sha256").write_text(f"{checksum}  {archive.name}\n")
            key = str(log.relative_to(root))
            self.assertTrue(check_archive(archive, None, {key: hashlib.sha256(log.read_bytes()).hexdigest()}, "8"))
            self.assertFalse(check_archive(archive, None, {key: "different"}, "8"))
            self.assertFalse(check_archive(archive, "bad checksum", {}, "8"))


class FakeProc:
    """A fake /proc: processes with argv, environment, parent and open fds, plus net/tcp and locks."""

    def __init__(self, root):
        self.root = root / "proc"
        self.queue = root / "slop-mq"
        self.queue.mkdir(parents=True)
        (self.queue / "queue.txt").write_text("")
        self.lock = self.queue / "trial-activity.lock"
        self.lock.write_text("")
        (self.root / "net").mkdir(parents=True)
        header = "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode\n"
        self.tcp = [header]
        self.tcp6 = [header]
        self.locks = []
        self.unreadable = set()

    def process(self, pid, argv, environ=None, ppid=1, sockets=(), lock=None, open_lock=False):
        directory = self.root / str(pid)
        (directory / "fd").mkdir(parents=True)
        (directory / "cmdline").write_bytes(b"\0".join(a.encode() for a in argv) + b"\0")
        (directory / "stat").write_text(f"{pid} ({Path(argv[0]).name[:15]}) S {ppid} {pid} {pid} 0 -1\n")
        (directory / "environ").write_bytes(b"".join(f"{k}={v}\0".encode() for k, v in (environ or {}).items()))
        for n, (inode, peer, state) in enumerate(sockets, start=3):
            os.symlink(f"socket:[{inode}]", directory / "fd" / str(n))
            table = self.tcp6 if len(peer.partition(":")[0]) == 32 else self.tcp
            table.append(f"   {len(table)}: 0100007F:9C40 {peer} {state} 00000000:00000000 00:00000000 00000000  1001        0 {inode}\n")
        if lock or open_lock:
            os.symlink(self.lock, directory / "fd" / "9")
        if lock:
            st = self.lock.stat()
            self.locks.append(f"{len(self.locks) + 1}: FLOCK  ADVISORY  {lock} {pid} "
                              f"{os.major(st.st_dev):02x}:{os.minor(st.st_dev):02x}:{st.st_ino} 0 EOF\n")

    def blockers(self, self_pid=1):
        (self.root / "net/tcp").write_text("".join(self.tcp))
        (self.root / "net/tcp6").write_text("".join(self.tcp6))
        (self.root / "locks").write_text("".join(self.locks))
        real = trial_reclaim.read_proc
        def read(path):
            if path in self.unreadable:
                raise PermissionError(path)
            return real(path)
        with patch("trial_reclaim.QUEUE", self.queue), patch("trial_reclaim.read_proc", side_effect=read):
            return blockers(self.root, self_pid=self_pid)


PRIVATE = {"LIVING_STDB_URL": "http://127.0.0.1:3397", "LIVING_STDB_CONTAINER": "verify-private-3397"}
TRIAL_PEER = "0100007F:0CF8"  # 127.0.0.1:3320


class BlockerTests(unittest.TestCase):
    def run_case(self, build):
        with tempfile.TemporaryDirectory() as tmp:
            fake = FakeProc(Path(tmp))
            fake.process(1, ["/sbin/init"])
            build(fake)
            return fake.blockers()

    def assertBlocks(self, build, reason):
        result = self.run_case(build)
        self.assertEqual(len(result), 1, result)
        self.assertRegex(result[0], "^active processes: " + reason)

    def test_private_server_drivers_do_not_block(self):
        def build(fake):
            # verify.py on a private server (3397/39201) and its mind, connected to that server.
            fake.process(100, ["python3", "/w/.agents/skills/verify/scripts/verify.py", "launch", "--run", "x"],
                         dict(PRIVATE, PATH="/usr/bin"))
            fake.process(101, ["/w/living/target/debug/living-mind"], PRIVATE, ppid=100,
                         sockets=[(7001, "0100007F:0D45", "01"), (7002, "0100007F:99A1", "01")])
            # verify.py on its default, the shared server on 3300.
            fake.process(102, ["python3", "verify.py", "doctor"])
            fake.process(103, ["python3", "-u", "living/tools/battle_diag.py"], PRIVATE)
            fake.process(104, ["python3", "living/tools/scene_gate.py", "run", "--stdb-container", "gate-private",
                               "--stdb-url", "http://127.0.0.1:3397"])
            fake.process(105, ["python3", "living/tools/trials.py", "run"],
                         {"TRIALS_STDB_CONTAINER": "trials-private", "TRIALS_STDB_PORT": "3397"})
            # A listening or closing socket on 3320 is not a connection; an unrelated process may connect.
            fake.process(106, ["python3", "verify.py", "launch"], PRIVATE, sockets=[(7003, TRIAL_PEER, "06")])
            fake.process(107, ["/usr/bin/curl", "http://127.0.0.1:3320/v1/ping"], sockets=[(7004, TRIAL_PEER, "01")])
            # Port 33201 and a similarly named container are not the trial server.
            fake.process(108, ["python3", "verify.py", "launch"],
                         {"LIVING_STDB_URL": "http://127.0.0.1:33201", "LIVING_STDB_CONTAINER": "slop-trials-stdb-copy"})
        self.assertEqual(self.run_case(build), [])

    def test_verify_pointed_at_trial_server_blocks(self):
        self.assertBlocks(lambda fake: fake.process(
            200, ["python3", "verify.py", "launch"], {"LIVING_STDB_URL": "http://127.0.0.1:3320"}),
            r"verify.py \(pid 200: LIVING_STDB_URL=http://127.0.0.1:3320\)$")
        self.assertBlocks(lambda fake: fake.process(
            201, ["python3", "verify.py", "launch"], dict(PRIVATE, LIVING_STDB_CONTAINER="slop-trials-stdb")),
            r"verify.py \(pid 201: LIVING_STDB_CONTAINER=slop-trials-stdb\)$")
        self.assertBlocks(lambda fake: fake.process(
            202, ["python3", "battle_diag.py"], dict(PRIVATE, TRIALS_STDB_PORT="3320")),
            r"battle_diag.py \(pid 202: TRIALS_STDB_PORT=3320\)$")

    def test_scene_gate_and_trials_default_to_trial_server(self):
        self.assertBlocks(lambda fake: fake.process(300, ["python3", "living/tools/scene_gate.py", "run"]),
                          r"scene_gate.py \(pid 300: default LIVING_GATE_STDB_CONTAINER=slop-trials-stdb\)$")
        # Overriding only the container still leaves the default URL on 3320.
        self.assertBlocks(lambda fake: fake.process(
            301, ["python3", "scene_gate.py", "run", "--stdb-container", "gate-private"]),
            r"scene_gate.py \(pid 301: default LIVING_GATE_STDB_URL=http://127.0.0.1:3320\)$")
        self.assertBlocks(lambda fake: fake.process(
            302, ["python3", "scene_gate.py", "run", "--stdb-url", "http://localhost:3320"]),
            r"scene_gate.py \(pid 302: argument 'http://localhost:3320'\)$")
        self.assertBlocks(lambda fake: fake.process(303, ["python3", "living/tools/trials.py", "run"]),
                          r"trials.py \(pid 303: default TRIALS_STDB_CONTAINER=slop-trials-stdb\)$")
        self.assertBlocks(lambda fake: fake.process(
            304, ["python3", "trials.py", "run"], {"TRIALS_STDB_CONTAINER": "trials-private"}),
            r"trials.py \(pid 304: default TRIALS_STDB_PORT=3320\)$")

    def test_connection_to_trial_server_blocks(self):
        def build(fake):
            fake.process(400, ["python3", "verify.py", "launch"], PRIVATE)
            fake.process(401, ["/bin/sh", "-c", "living-mind"], PRIVATE, ppid=400)
            fake.process(402, ["living-mind"], PRIVATE, ppid=401, sockets=[(8001, TRIAL_PEER, "01")])
        self.assertBlocks(build, r"verify.py \(pid 400: connected to 127.0.0.1:3320 through pid 402\)$")
        self.assertBlocks(lambda fake: fake.process(
            403, ["python3", "verify.py"], PRIVATE,
            sockets=[(8002, "0000000000000000FFFF00000100007F:0CF8", "01")]),
            r"verify.py \(pid 403: connected to 127.0.0.1:3320\)$")

    def test_trial_activity_lock_holder_blocks(self):
        self.assertBlocks(lambda fake: fake.process(
            500, ["python3", "battle_diag.py"], PRIVATE, lock="READ"),
            r"battle_diag.py \(pid 500: holds trial-activity.lock\)$")
        def build(fake):
            # `flock -s` holds the lock; its child shares the open file.
            fake.process(501, ["flock", "-s", str(fake.lock), "python3", "x.py"], lock="READ")
            fake.process(502, ["python3", "x.py"], ppid=501, open_lock=True)
        self.assertBlocks(build, r"flock \(pid 501: holds trial-activity.lock\), python3 \(pid 502: holds trial-activity.lock\)$")
        # The reclaim's own exclusive lock is not a blocker, nor are waiters behind it.
        def own(fake):
            fake.process(503, ["python3", "trial_reclaim.py"], lock="WRITE")
            fake.process(504, ["flock", "-s", str(fake.lock), "true"], open_lock=True)
        with tempfile.TemporaryDirectory() as tmp:
            fake = FakeProc(Path(tmp))
            own(fake)
            self.assertEqual(fake.blockers(self_pid=503), [])

    def test_unreadable_environment_blocks(self):
        def build(fake):
            fake.process(600, ["python3", "verify.py", "launch"], PRIVATE)
            fake.unreadable.add(fake.root / "600" / "environ")
        self.assertBlocks(build, r"verify.py \(pid 600: environment unreadable\)$")

    def test_merge_queue_scripts_always_block(self):
        self.assertBlocks(lambda fake: fake.process(700, ["bash", "/home/u/slop-mq/drain.sh"], PRIVATE),
                          r"drain.sh \(pid 700: merge queue\)$")
        self.assertBlocks(lambda fake: fake.process(701, ["/home/u/slop-mq/merge2.sh", "b"]),
                          r"merge2.sh \(pid 701: merge queue\)$")


if __name__ == "__main__":
    unittest.main()
