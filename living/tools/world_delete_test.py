#!/usr/bin/env python3
"""Checks of world_delete.pause_and_delete with fake servers: python3 living/tools/world_delete_test.py"""
import world_delete as wd


def run(pause_code, reads, gone_after=True):
    calls = []
    reads = list(reads)
    out = wd.pause_and_delete(
        pause=lambda: (calls.append("pause"), pause_code)[1],
        read=lambda: (calls.append("read"), reads.pop(0) if reads else (200, "false"))[1],
        delete=lambda: calls.append("delete"),
        gone=lambda: gone_after,
        sleep=lambda s: calls.append(f"sleep {s}"))
    return out, calls


# Paused at the second read: waits 1 s between reads, 2 s before the delete, then deletes.
(ok, why), calls = run(200, [(200, "false"), (200, "true")])
assert ok and why == "deleted (SQL now 404)", why
assert calls == ["pause", "read", "sleep 1", "read", "sleep 2.0", "delete"], calls
# Never paused within 10 reads: not deleted, and says why.
(ok, why), calls = run(200, [(200, "false")] * 10)
assert not ok and "could not be read back as paused" in why and "delete" not in calls, (why, calls)
# A 404 at the pause or at a read counts as deleted, with nothing deleted.
(ok, why), calls = run(404, [])
assert ok and "delete" not in calls
(ok, why), calls = run(200, [(404, "")])
assert ok and "delete" not in calls
# Deleted but still answering: reported.
(ok, why), _ = run(200, [(200, "true")], gone_after=False)
assert not ok and "still answers" in why
print("world_delete: 5 checks pass")
