#!/usr/bin/env python3
"""Load this endpoint's local JSON credential and replace this process with sao-sim."""
import argparse
import json
import os
from pathlib import Path
import stat
import sys

ROOT = Path(__file__).resolve().parents[1]
CREDENTIAL = ROOT / ".local/credentials/codex-carlid.json"
CONFIG = ROOT / "configs/reasoning/codex-carlid-luna.json"


def load_key(path):
    # Never evaluate file contents or include parser exceptions/key values in errors.
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            raise ValueError("Credential must be a regular file owned by you.")
        if stat.S_IMODE(info.st_mode) & 0o077:
            raise ValueError("Credential permissions must be owner-only; use chmod 600.")
        value = json.loads(path.read_text())
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise ValueError("Cannot read local credential JSON; open the template and save valid JSON.") from None
    key = value.get("api_key") if isinstance(value, dict) else None
    if not isinstance(key, str) or not key.strip():
        raise ValueError("Fill api_key in .local/credentials/codex-carlid.json before running.")
    if any(c.isspace() or ord(c) < 32 or ord(c) > 126 for c in key):
        raise ValueError("api_key must contain only printable ASCII without whitespace.")
    return key


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", help="new run archive directory, relative to repository root")
    parser.add_argument("--scenario", default="scenarios/survival.json")
    parser.add_argument("--config", default=str(CONFIG), help="reasoning config for the same Carlid endpoint")
    parser.add_argument("--port", type=int, default=18881)
    parser.add_argument("--probe-state", help="one hosted generation against a frozen authority state; no simulation loop")
    args = parser.parse_args()
    config_path = ROOT / args.config
    try:
        selected = json.loads(config_path.read_text())
        backend = selected["backend"]
        if backend.get("kind") != "openai_compatible" or backend.get("base_url") != "https://codex.carlid.dev/v1" or backend.get("auth") != {"kind":"bearer_env","credential_env":"CARLID_NPC_API_KEY"}:
            raise ValueError("Selected config must use the prepared Carlid endpoint and credential reference.")
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, AttributeError):
        print("Cannot read a valid Carlid reasoning config.", file=sys.stderr)
        return 2
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 2
    try:
        key = load_key(CREDENTIAL)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 2
    runner = ROOT / ("target/debug/examples/hosted_policy_probe" if args.probe_state else "target/debug/sao-sim")
    if not runner.is_file():
        print("Build first: cargo build -p bridge --bin sao-sim", file=sys.stderr)
        return 2
    env = os.environ.copy()
    env["CARLID_NPC_API_KEY"] = key
    env["NPC_REASONING_CONFIG"] = str(config_path)
    env.setdefault("SIM_TICK_MS", "8000")
    os.chdir(ROOT)
    # The credential is inherited only as an environment value, never an argument.
    command = [str(runner), str(ROOT / args.probe_state), str(config_path), args.output] if args.probe_state else [str(runner), "run", args.scenario, args.output, "configured", str(args.port)]
    os.execve(runner, command, env)


if __name__ == "__main__":
    sys.exit(main())
