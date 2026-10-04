#!/usr/bin/env python3
"""Run the core's offline Cargo checks and retain each command and result."""
import argparse
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
CHECKS = {
    "rules": ["-p", "living-rules"],
    "authority-seed": ["-p", "living-authority", "--lib", "seed::tests"],
    "mind": ["-p", "living-mind"],
    "viewer-sync": ["-p", "living-viewer", "sync::tests"],
}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run", required=True)
    a = ap.parse_args()
    if not re.fullmatch(r"core-[a-z0-9-]+", a.run):
        ap.error("use a core-* run name with lowercase letters, digits and hyphens")
    out = ROOT / ".local/living/verify" / a.run
    out.mkdir(parents=True, exist_ok=True)
    results = {}
    for name, flags in CHECKS.items():
        cmd = ["cargo", "test", "--manifest-path", "living/Cargo.toml", *flags]
        with (out / f"{name}.txt").open("w") as f:
            f.write("COMMAND " + " ".join(cmd) + "\n")
            f.flush()
            code = subprocess.run(cmd, cwd=ROOT, stdout=f, stderr=subprocess.STDOUT).returncode
        log = (out / f"{name}.txt").read_text()
        summaries = re.findall(r"test result: (.*)", log)
        results[name] = {"command": cmd, "exit": code, "summaries": summaries}
        print(("PASS " if code == 0 else "FAIL ") + name + " " + "; ".join(summaries), flush=True)
    (out / "cargo-results.json").write_text(json.dumps(results, indent=2) + "\n")
    return int(any(r["exit"] for r in results.values()))


if __name__ == "__main__":
    raise SystemExit(main())
