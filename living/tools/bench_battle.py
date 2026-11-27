#!/usr/bin/env python3
"""Measure one uncapped High-quality rep at Play Middle in a live Cullet battle.

Stages two sides of 100 spear fighters at noon. Samples 12 seconds after a
3.5-second warmup, then captures the scene and deletes the scratch world.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from lookdev_shoot import REPO, VERIFY_PY, parse_frames_csv, resolve_binary

sys.path.insert(0, str(REPO / ".agents/skills/verify-ui/scripts"))
from check import call_admin, sql, staged_drive, verify_sql_noon


def build_parser():
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog="Set LIVING_STDB_CONTAINER and LIVING_STDB_URL for a dedicated server, "
               "and CARGO_TARGET_DIR for the scratch authority build.",
    )
    parser.add_argument("--run", required=True, help="Fresh verify run name, without the verify- prefix.")
    parser.add_argument("--out", required=True, type=Path, help="Directory for frame CSVs, summary, and scene evidence.")
    parser.add_argument("--size", required=True, help="Headless output size in pixels, for example 1920x1080.")
    parser.add_argument("--look", choices=("classic", "lookdev"), required=True, help="Lighting preset.")
    parser.add_argument("--scale", choices=("75", "100"), required=True, help="Fixed internal render scale, in percent.")
    parser.add_argument("--bin", help="Release client path. Defaults to lookdev_shoot's binary search.")
    return parser


def summarize_sample(frames, client_log, sample):
    marker = re.search(r"^(\S+).*live script: wait:12 \(", client_log, re.MULTILINE)
    if marker is None:
        raise RuntimeError("missing sample start marker in client.log")
    start = round(datetime.fromisoformat(marker[1]).timestamp() * 1_000_000)
    end = start + 12_000_000
    lines = frames.read_text().splitlines()
    sample.write_text("".join(line + "\n" for line in lines
                              if start <= int(line.split(",", 1)[0]) < end))
    stats = parse_frames_csv(sample, warmup_s=0)
    if stats.get("steady_span_s", 0) < 11.8:
        raise RuntimeError(f"incomplete frame sample: {stats}")
    return dict(stats, sample_start_unix_us=start, sample_end_unix_us=end)


def main():
    parser = build_parser()
    args = parser.parse_args()
    if os.environ.get("LIVING_STDB_CONTAINER") in (None, "", "sao-living_spacetimedb_1") or not os.environ.get("LIVING_STDB_URL"):
        parser.error("set LIVING_STDB_CONTAINER and LIVING_STDB_URL for a dedicated server")
    run, out = args.run, args.out.resolve()
    target = os.environ.get("CARGO_TARGET_DIR")
    if not target:
        parser.error("set CARGO_TARGET_DIR for the scratch authority build")
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", run) or len(run) > 56:
        parser.error("--run must be a lowercase verify run name of at most 56 characters")
    if not re.fullmatch(r"[1-9]\d*x[1-9]\d*", args.size):
        parser.error("--size must be WIDTHxHEIGHT with positive dimensions")
    state = REPO / ".local/living/verify" / run / "state.json"
    if state.exists():
        parser.error("--run must name a fresh verify run")
    client = resolve_binary(args.bin)
    out.mkdir(parents=True, exist_ok=True)
    verify = [sys.executable, str(VERIFY_PY)]
    frames = out / "frames.csv"
    env = dict(LIVING_GAME_FPS_CAP="0", LIVING_GAME_FRAMES=str(frames),
               LIVING_GAME_QUALITY="high", LIVING_GAME_LOOK=args.look,
               LIVING_GAME_RENDER_SCALE=args.scale, LIVING_GAME_WEATHER="clear")

    def fighters():
        return [row for row in sql(run, "SELECT id, name, alive FROM character WHERE kind = 'person'", check=True)
                if re.fullmatch(r"[AB]\d+", row["name"] or "")]

    def battle(me, _identity):
        verify_sql_noon(run)
        call_admin(run, "spawn_battle_sides_layout", [200, 2, 42, 0], check=True)
        people = fighters()
        ids = {row["id"] for row in people}
        if len(ids) != 200:
            raise RuntimeError(f"spawned {len(ids)} fighters, expected 200")
        pos = [row for row in sql(run, "SELECT id, x, y FROM body", check=True) if row["id"] in ids]
        centre = [sum(row[axis] for row in pos) / len(pos) for axis in ("x", "y")]
        call_admin(run, "place_at", [me, centre[0], centre[1] + 9], check=True)
        return {"centre": centre, "fighter_ids": sorted(ids), "alive": sum(row["alive"] for row in people)}

    try:
        subprocess.run([*verify, "launch", "--run", run, "--seed", "cullet", "--target-dir",
                        str(Path(target).resolve())], cwd=REPO, check=True)
        evidence, code, log, syncs = staged_drive(
            run, "battle-bench",
            "ready;frame:0;sync:battle;look:0;wait:3.5;wait:12;dump:bench;shot:battle_middle;quit",
            {"battle": battle}, extra=["--size", args.size, "--client", str(client)], env=env, timeout=180,
        )
        (out / "drive.log").write_text(log)
        for path in Path(evidence).iterdir():
            if path.name in {"bench.json", "battle_middle.png", "client.log", "plan.txt", "scene.json", "syncs.json"}:
                shutil.copy2(path, out / path.name)
        if code or len(syncs.get("battle", {}).get("fighter_ids", [])) != 200:
            raise RuntimeError(f"battle drive exit {code}, syncs {syncs}")
        people = fighters()
        (out / "fighters_after.json").write_text(json.dumps(people, indent=2) + "\n")
        stats = summarize_sample(frames, (out / "client.log").read_text(), out / "sample.csv")
        (out / "frametime_summary.json").write_text(json.dumps(stats, indent=2) + "\n")
    finally:
        if state.exists():
            subprocess.run([*verify, "cleanup", "--run", run], cwd=REPO, check=True)


if __name__ == "__main__":
    main()
