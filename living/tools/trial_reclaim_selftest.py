#!/usr/bin/env python3
"""Exercise reclaim decisions and exact archive matching on a fake replica tree."""
import collections
import hashlib
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path

from trial_reclaim import HAMLETS, check_archive, plan


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


if __name__ == "__main__":
    unittest.main()
