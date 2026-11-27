#!/usr/bin/env python3
"""Frozen stop-rule guard for the §7 neural-body pilot (docs/NEURAL_BODY.md "Pilot run").

Every stop rule frozen in docs/NEURAL_BODY.md is enforced in code here and dry-run
via `--dry-run-stops` before any data collection, training, or evaluation runs.
"""
import argparse
import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BATTLE_LOCK = Path.home() / "slop-mq" / "battle.lock"

# Frozen thresholds from docs/NEURAL_BODY.md ("Pilot run", §5).
MIN_FREE_MEM_GIB = 40.0
MIN_FREE_DISK_GIB = 60.0
MAX_CAPTURE_MIB = 512.0
MAX_DECISION_P95_MS = 50.0
MAX_LAPSE_SHARE = 0.05
MAX_TOO_MANY_INPUTS_SHARE = 0.10
MAX_COLLECTED_DECISIONS = 160_000
MAX_TRAIN_EPOCHS = 40
MAX_EVAL_EPISODES = 10


class StopRuleViolation(RuntimeError):
    def __init__(self, code: str, detail: str):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


def check_no_cuda():
    """STOP_BUDGET_CAP: CPU-only pilot — forbid CUDA modules/env."""
    for mod in ("torch", "cupy", "numba.cuda"):
        if mod in sys.modules:
            raise StopRuleViolation("STOP_BUDGET_CAP", f"forbidden GPU module imported: {mod}")
    if os.environ.get("LIVING_BODY_ALLOW_CUDA") == "1":
        raise StopRuleViolation("STOP_BUDGET_CAP", "CUDA explicitly requested in CPU-only pilot")


def check_battle_lock(lock_path: Path = BATTLE_LOCK):
    """STOP_BUDGET_CAP: never run measurements while ~/slop-mq/battle.lock is held."""
    if not lock_path.exists():
        return
    with lock_path.open("r+") as f:
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        except BlockingIOError:
            raise StopRuleViolation("STOP_BUDGET_CAP", f"{lock_path} is currently held by another measurement")


def mem_available_gib() -> float:
    with open("/proc/meminfo") as f:
        for line in f:
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) / (1024.0 * 1024.0)
    return 0.0


def disk_free_gib(path: Path = Path.home()) -> float:
    st = shutil.disk_usage(path)
    return st.free / (1024.0 ** 3)


def dir_size_mib(path: Path) -> float:
    if not path.exists():
        return 0.0
    total = 0
    for p in path.rglob("*"):
        if p.is_file():
            total += p.stat().st_size
    return total / (1024.0 * 1024.0)


def check_resources(capture_dir: Path | None = None,
                    mem_gib: float | None = None,
                    disk_gib: float | None = None,
                    cap_mib: float | None = None):
    """STOP_RESOURCE: enforce memory >= 40 GiB, disk >= 60 GiB, capture <= 512 MiB."""
    m = mem_available_gib() if mem_gib is None else mem_gib
    if m < MIN_FREE_MEM_GIB:
        raise StopRuleViolation("STOP_RESOURCE", f"MemAvailable {m:.1f} GiB < {MIN_FREE_MEM_GIB} GiB floor")
    d = disk_free_gib() if disk_gib is None else disk_gib
    if d < MIN_FREE_DISK_GIB:
        raise StopRuleViolation("STOP_RESOURCE", f"Free disk {d:.1f} GiB < {MIN_FREE_DISK_GIB} GiB floor")
    if capture_dir is not None or cap_mib is not None:
        c = dir_size_mib(capture_dir) if cap_mib is None else cap_mib
        if c > MAX_CAPTURE_MIB:
            raise StopRuleViolation("STOP_RESOURCE", f"Capture dir {c:.1f} MiB > {MAX_CAPTURE_MIB} MiB limit")


def check_plumbing_encounters(replicate_exposures: list[int]):
    """STOP_NO_ENCOUNTER: stop after 2 plumbing replicates if neither yields >= 1 exposure."""
    if len(replicate_exposures) >= 2 and all(e < 1 for e in replicate_exposures[:2]):
        raise StopRuleViolation(
            "STOP_NO_ENCOUNTER",
            f"first two plumbing replicates yielded {replicate_exposures[:2]} scoreable exposures (< 1)"
        )


def check_hashes(wasm_path: Path, expected_wasm_sha: str,
                 skills_sha: str, expected_skills_sha: str):
    """STOP_HASH_MISMATCH: verify authority WASM and skills script SHA-256."""
    actual_wasm = hashlib.sha256(wasm_path.read_bytes()).hexdigest()
    if actual_wasm != expected_wasm_sha:
        raise StopRuleViolation("STOP_HASH_MISMATCH", f"WASM hash {actual_wasm[:12]} != expected {expected_wasm_sha[:12]}")
    if skills_sha != expected_skills_sha:
        raise StopRuleViolation("STOP_HASH_MISMATCH", f"skills.rhai hash {skills_sha[:12]} != expected {expected_skills_sha[:12]}")


def check_leakage(encode_tests_ok: bool, leaked_frames: int = 0):
    """STOP_LEAKAGE: fail on encode leakage test failure or any leaked capture frame."""
    if not encode_tests_ok:
        raise StopRuleViolation("STOP_LEAKAGE", "body::encode::tests failed")
    if leaked_frames > 0:
        raise StopRuleViolation("STOP_LEAKAGE", f"detected {leaked_frames} leaked perception frames")


def check_replay_determinism(hash_a: str, hash_b: str, body_delegate_on: bool = True):
    """STOP_REPLAY_DIVERGENCE: deterministic forward pass & world law check."""
    if hash_a != hash_b:
        raise StopRuleViolation("STOP_REPLAY_DIVERGENCE", f"deterministic forward-pass hash {hash_a} != {hash_b}")
    if not body_delegate_on:
        raise StopRuleViolation("STOP_REPLAY_DIVERGENCE", "body_delegate_on law drifted off")


def check_timing_and_inputs(decision_p95_ms: float, epochs: int, lapses: int,
                            total_calls: int, too_many_inputs: int):
    """STOP_BUDGET_MISS: check decision loop p95, lease lapse share, input-bucket refusals."""
    if decision_p95_ms > MAX_DECISION_P95_MS:
        raise StopRuleViolation("STOP_BUDGET_MISS", f"decision p95 {decision_p95_ms:.1f} ms > {MAX_DECISION_P95_MS} ms")
    if epochs > 0 and (lapses / epochs) > MAX_LAPSE_SHARE:
        raise StopRuleViolation("STOP_BUDGET_MISS", f"lease lapses {lapses}/{epochs} ({100*lapses/epochs:.1f}%) > {100*MAX_LAPSE_SHARE:.0f}%")
    if total_calls > 0 and (too_many_inputs / total_calls) > MAX_TOO_MANY_INPUTS_SHARE:
        raise StopRuleViolation("STOP_BUDGET_MISS", f"too_many_inputs {too_many_inputs}/{total_calls} ({100*too_many_inputs/total_calls:.1f}%) > {100*MAX_TOO_MANY_INPUTS_SHARE:.0f}%")


def check_budgets(decisions: int = 0, epochs: int = 0, eval_episodes: int = 0):
    """STOP_BUDGET_CAP: hard caps on collection, training, and evaluation budgets."""
    check_no_cuda()
    if decisions > MAX_COLLECTED_DECISIONS:
        raise StopRuleViolation("STOP_BUDGET_CAP", f"collected decisions {decisions} > {MAX_COLLECTED_DECISIONS}")
    if epochs > MAX_TRAIN_EPOCHS:
        raise StopRuleViolation("STOP_BUDGET_CAP", f"training epochs {epochs} > {MAX_TRAIN_EPOCHS}")
    if eval_episodes > MAX_EVAL_EPISODES:
        raise StopRuleViolation("STOP_BUDGET_CAP", f"eval episodes {eval_episodes} > {MAX_EVAL_EPISODES}")


def dry_run_stops(out_path: Path | None = None) -> dict:
    """Deliberately trip every frozen stop rule and verify each raises the right StopRuleViolation."""
    tmp_file = Path("/tmp/nb_guard_dummy.wasm")
    tmp_file.write_bytes(b"dummy-wasm")
    dummy_sha = hashlib.sha256(b"dummy-wasm").hexdigest()
    cases = [
        ("STOP_NO_ENCOUNTER", lambda: check_plumbing_encounters([0, 0])),
        ("STOP_LEAKAGE_TESTS", lambda: check_leakage(False, 0)),
        ("STOP_LEAKAGE_FRAME", lambda: check_leakage(True, 3)),
        ("STOP_HASH_MISMATCH_WASM", lambda: check_hashes(tmp_file, "0" * 64, "a" * 64, "a" * 64)),
        ("STOP_HASH_MISMATCH_SKILLS", lambda: check_hashes(tmp_file, dummy_sha, "a" * 64, "b" * 64)),
        ("STOP_REPLAY_DIVERGENCE_HASH", lambda: check_replay_determinism("abc", "def", True)),
        ("STOP_REPLAY_DIVERGENCE_LAW", lambda: check_replay_determinism("abc", "abc", False)),
        ("STOP_BUDGET_MISS_P95", lambda: check_timing_and_inputs(65.0, 10, 0, 100, 0)),
        ("STOP_BUDGET_MISS_LAPSE", lambda: check_timing_and_inputs(5.0, 10, 1, 100, 0)),
        ("STOP_BUDGET_MISS_INPUTS", lambda: check_timing_and_inputs(5.0, 10, 0, 100, 15)),
        ("STOP_RESOURCE_MEM", lambda: check_resources(mem_gib=30.0, disk_gib=90.0, cap_mib=10.0)),
        ("STOP_RESOURCE_DISK", lambda: check_resources(mem_gib=80.0, disk_gib=45.0, cap_mib=10.0)),
        ("STOP_RESOURCE_CAPTURE", lambda: check_resources(mem_gib=80.0, disk_gib=90.0, cap_mib=600.0)),
        ("STOP_BUDGET_CAP_DECISIONS", lambda: check_budgets(decisions=200_000)),
        ("STOP_BUDGET_CAP_EPOCHS", lambda: check_budgets(epochs=50)),
        ("STOP_BUDGET_CAP_EVAL", lambda: check_budgets(eval_episodes=12)),
    ]
    results = []
    all_ok = True
    for name, fn in cases:
        expected_prefix = "_".join(name.split("_")[:3]) if name.startswith("STOP_BUDGET") or name.startswith("STOP_HASH") or name.startswith("STOP_REPLAY") or name.startswith("STOP_NO") else "_".join(name.split("_")[:2])
        try:
            fn()
            results.append({"case": name, "tripped": False, "error": "did not raise"})
            all_ok = False
        except StopRuleViolation as e:
            ok = e.code == expected_prefix
            results.append({"case": name, "tripped": True, "code": e.code, "detail": e.detail, "ok": ok})
            if not ok:
                all_ok = False
    tmp_file.unlink(missing_ok=True)
    # Also verify live host health passes right now (positive control).
    live = {"mem_available_gib": round(mem_available_gib(), 2), "disk_free_gib": round(disk_free_gib(), 2)}
    try:
        check_resources()
        check_no_cuda()
        check_battle_lock()
        live["healthy"] = True
    except StopRuleViolation as e:
        live["healthy"] = False
        live["violation"] = str(e)
    report = {"all_stops_tripped": all_ok, "cases": results, "live_host": live}
    if out_path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, indent=2) + "\n")
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run-stops", action="store_true", help="trip every frozen stop rule and exit 0 only if all trip")
    ap.add_argument("--out", type=Path, help="write JSON report")
    a = ap.parse_args()
    if a.dry_run_stops:
        rep = dry_run_stops(a.out)
        print(json.dumps({"all_stops_tripped": rep["all_stops_tripped"], "count": len(rep["cases"]), "live_host": rep["live_host"]}, indent=2))
        return 0 if rep["all_stops_tripped"] else 1
    check_resources()
    check_no_cuda()
    check_battle_lock()
    print(json.dumps({"healthy": True, "mem_available_gib": round(mem_available_gib(), 2), "disk_free_gib": round(disk_free_gib(), 2)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
