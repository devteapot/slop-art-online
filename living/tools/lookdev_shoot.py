#!/usr/bin/env python3
"""Shared look-dev shoot tool for Slop Art Online (macOS and Linux/AMD dev-box).

Reproduces the locked look-dev scenes under identical Cullet world lighting,
atmosphere, post-processing and camera poses:

  1. Mode A (`characters`, default) — Offline asset stage (`LIVING_GAME_VIEW`
     with Cullet atmosphere, clear weather, frozen clock): shoots any `.glb`,
     `recipe:...` or `look:...` across Noon (12.0), Dusk (17.7) and Night (22.5)
     at the 5 locked camera poses (portrait close-up, 3/4 full-body, 3/4 back-rim,
     Play Near, Play Middle), stitches a contact sheet per character, and
     optionally runs the orthographic measuring view (`--ortho`).
  2. Mode B (`plaza`) — Live Cullet Counting House yard plaza via `verify.py` +
     `drive.py` on a scratch `verify-ui-lookdev-*` world: 14 held residents,
     Play Middle and Near stops across Noon, Dusk and Night (6 stills + sheet),
     or uncapped steady-state frame-time benchmarking (`--bench`).
  3. `both` — Runs `characters` then `plaza`.

Zero hard-coded host paths: locates the release `living-game` binary via
`--bin`, `$LIVING_GAME_BIN`, `$CARGO_TARGET_DIR/release/living-game`,
`.local/target/release/living-game`, or `living/target/release/living-game`.

Examples:
  # Dev-box stage 3+: shoot a new character GLB beside a reference Cullet look
  python3 living/tools/lookdev_shoot.py \\
    --models "living/game/assets/view/hero.glb,look:lk_5715bc7d45d32adf" \\
    --out .local/living/lookdev/stage3

  # Shoot with explicit quality / render-scale / look settings
  python3 living/tools/lookdev_shoot.py \\
    --mode plaza --size 1920x1080 --quality medium --render-scale 75 \\
    --out .local/living/lookdev/plaza-med75

  # Benchmark busy Cullet plaza (Middle, Noon, uncapped)
  python3 living/tools/lookdev_shoot.py \\
    --mode plaza --bench --size 3024x1964 --quality medium --render-scale 75 \\
    --out .local/living/lookdev/bench-med75
"""

import argparse
import datetime as dt
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
VERIFY_PY = REPO / ".agents/skills/verify/scripts/verify.py"
DRIVE_PY = REPO / ".agents/skills/verify-ui/scripts/drive.py"

DEFAULT_MODELS = (
    "look:lk_5715bc7d45d32adf,"  # Mirren Quill (adult-f-a, teal smock, brown braid)
    "look:lk_650c702f194b7d76,"  # Imre Sarro (adult-m-b, burgundy jersey, dark hair)
    "look:lk_5edbeda57773525d"   # Ode Pontil (elder-m-b, slate-blue jersey, silver-grey hair)
)

TIME_PRESETS = {
    "noon": 12.0,
    "dusk": 17.7,
    "night": 22.5,
}

# Locked 5 camera poses (portrait, 3/4 front, 3/4 back-rim, Play Near, Play Middle).
DEFAULT_SHOTS = (
    "idle@0/0:8:0.36:0.88,"
    "idle@0/35:14:0.85,"
    "idle@0/145:14:0.85,"
    "idle@0/near@0,"
    "idle@0/middle@0"
)

# Locked Counting House yard plaza anchor & 14 held Cullet residents.
PLAZA_ANCHOR = (536.5, 767.5)
PLAZA_CROWD = [
    "10:2.0:-1.8",
    "2:-2.0:-1.8",
    "1:0.2:-3.5",
    "3:3.8:-3.0",
    "4:-4.2:-2.5",
    "5:5.5:-0.5",
    "6:-5.2:0.5",
    "8:1.8:-5.2",
    "9:-2.8:-5.0",
    "11:7.2:-3.2",
    "12:-6.8:-3.5",
    "13:6.8:1.8",
    "14:2.8:2.2",
    "15:-3.2:2.0",
]


def parse_time_token(tok: str) -> tuple[str, float]:
    key = tok.strip().lower()
    if key in TIME_PRESETS:
        return key, TIME_PRESETS[key]
    try:
        hr = float(key)
    except ValueError:
        sys.exit(f"lookdev_shoot: unknown time preset or hour: {tok!r} (use noon, dusk, night, or a number)")
    tag = f"h{str(hr).replace('.', '_')}"
    return tag, hr


def resolve_binary(explicit: str | None) -> Path:
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit).expanduser())
    if os.environ.get("LIVING_GAME_BIN"):
        candidates.append(Path(os.environ["LIVING_GAME_BIN"]).expanduser())
    if os.environ.get("CARGO_TARGET_DIR"):
        candidates.append(Path(os.environ["CARGO_TARGET_DIR"]).expanduser() / "release/living-game")
    candidates.append(REPO / ".local/target/release/living-game")
    candidates.append(REPO / "living/target/release/living-game")
    for p in candidates:
        if p.is_file() and os.access(p, os.X_OK):
            return p.resolve()
    tried = "\n  ".join(str(p) for p in candidates)
    sys.exit(
        "lookdev_shoot: no executable release living-game binary found.\n"
        f"Tried:\n  {tried}\n"
        "Build it with `cargo build --release --manifest-path living/Cargo.toml -p living-game` "
        "or pass `--bin PATH`."
    )


def git_info() -> dict:
    def run_git(*args: str) -> str:
        r = subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True)
        return r.stdout.strip() if r.returncode == 0 else ""

    return {
        "commit": run_git("rev-parse", "HEAD"),
        "short": run_git("rev-parse", "--short", "HEAD"),
        "branch": run_git("rev-parse", "--abbrev-ref", "HEAD"),
        "dirty": bool(run_git("status", "--porcelain", "--untracked-files=no")),
    }


def apply_setting_env(env: dict[str, str], args: argparse.Namespace) -> None:
    """Apply explicit look, quality, render-scale, weather and custom LIVING_GAME_* flags."""
    env.setdefault("LIVING_GAME_WEATHER", "clear")
    if args.weather is not None:
        env["LIVING_GAME_WEATHER"] = args.weather
    if args.quality is not None:
        env["LIVING_GAME_QUALITY"] = args.quality
    if args.render_scale is not None:
        env["LIVING_GAME_RENDER_SCALE"] = args.render_scale
    if args.film is not None:
        env["LIVING_GAME_FILM"] = args.film
    if args.hair_shine is not None:
        env["LIVING_GAME_HAIR_SHINE"] = args.hair_shine
    if args.look is not None:
        env["LIVING_GAME_LOOK"] = args.look
    if args.perf is not None:
        env["LIVING_GAME_PERF"] = args.perf
    for item in args.env:
        if "=" not in item:
            sys.exit(f"lookdev_shoot: --env expects KEY=VALUE, got {item!r}")
        k, v = item.split("=", 1)
        env[k.strip()] = v


def stitch_grid(out_path: Path, rows: list[list[Path]], cell: tuple[int, int] = (640, 360)) -> bool:
    """Stitch a 2D grid of images into one PNG via Pillow, ImageMagick montage, or uv+Pillow."""
    if not rows or not any(rows):
        return False
    cw, ch = cell
    pad = 2
    ncols = max(len(r) for r in rows)
    nrows = len(rows)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        from PIL import Image

        sheet = Image.new("RGB", (ncols * (cw + 2 * pad), nrows * (ch + 2 * pad)), (32, 32, 32))
        for ri, row in enumerate(rows):
            for ci, img_path in enumerate(row):
                if not img_path.is_file():
                    continue
                im = Image.open(img_path).convert("RGB")
                im.thumbnail((cw, ch))
                x = ci * (cw + 2 * pad) + pad + (cw - im.width) // 2
                y = ri * (ch + 2 * pad) + pad + (ch - im.height) // 2
                sheet.paste(im, (x, y))
        sheet.save(out_path)
        return True
    except ImportError:
        pass

    flat = [str(p) for row in rows for p in row if p.is_file()]
    if not flat:
        return False
    if shutil.which("montage"):
        r = subprocess.run(
            ["montage", *flat, "-geometry", f"{cw}x{ch}+{pad}+{pad}", "-tile", f"{ncols}x{nrows}", "-background", "#202020", str(out_path)],
            capture_output=True,
        )
        if r.returncode == 0 and out_path.is_file():
            return True
    if shutil.which("uv"):
        r = subprocess.run(
            ["uv", "run", "--quiet", "--with", "pillow", "python3", str(REPO / "living/tools/contact_sheet.py"), str(out_path), "--cols", str(ncols), "--cell", f"{cw}x{ch}", *flat],
            capture_output=True,
        )
        if r.returncode == 0 and out_path.is_file():
            return True
    print(f"lookdev_shoot: Pillow/montage/uv not available; skipping contact sheet {out_path.name}", file=sys.stderr)
    return False


def run_characters(bin_path: Path, out_dir: Path, times: list[tuple[str, float]], args: argparse.Namespace) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    models = args.models or DEFAULT_MODELS
    shots = args.shots or DEFAULT_SHOTS
    reports: dict[str, object] = {}

    for tag, hr in times:
        sub = out_dir / tag
        sub.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ)
        apply_setting_env(env, args)
        env.update(
            {
                "LIVING_GAME_VIEW": models,
                "LIVING_GAME_VIEW_ENV": args.env_id,
                "LIVING_GAME_VIEW_ATMO": "1",
                "LIVING_GAME_DAY_MINUTES": "0",
                "LIVING_GAME_HOUR": f"{hr:g}",
                "LIVING_GAME_SIZE": args.size,
                "LIVING_GAME_VIEW_SHOTS": shots,
                "LIVING_GAME_VIEW_OUT": str(sub),
                "RUST_LOG": os.environ.get("RUST_LOG", "warn,living_game=info"),
            }
        )
        if args.clip:
            env["LIVING_GAME_VIEW_CLIP"] = args.clip
        if args.plate:
            env["LIVING_GAME_VIEW_PLATE"] = "1"
        print(f"lookdev_shoot: [characters/{tag} @ {hr:g}h] -> {sub}", flush=True)
        r = subprocess.run([str(bin_path)], cwd=REPO, env=env)
        if r.returncode != 0:
            sys.exit(f"lookdev_shoot: living-game exited {r.returncode} on characters/{tag}")
        rep = sub / "report.json"
        if rep.is_file():
            try:
                reports[tag] = json.loads(rep.read_text())
            except ValueError:
                pass

    # Stitch one contact sheet per model across times (rows = times, cols = shots).
    model_names: list[str] = []
    seen: set[str] = set()
    for tag, _ in times:
        sub = out_dir / tag
        for child in sorted(sub.iterdir()):
            if child.is_dir() and child.name not in seen:
                seen.add(child.name)
                model_names.append(child.name)

    sheets: list[str] = []
    if not args.no_sheet:
        for name in model_names:
            grid: list[list[Path]] = []
            for tag, _ in times:
                d = out_dir / tag / name
                imgs = sorted(d.glob("[0-9][0-9]-*.png")) if d.is_dir() else []
                grid.append(imgs)
            sheet_path = out_dir / f"{name}.png"
            if stitch_grid(sheet_path, grid):
                sheets.append(str(sheet_path))
                print(f"lookdev_shoot: contact sheet -> {sheet_path}", flush=True)

    ortho_dir = None
    if args.ortho:
        ortho_dir = out_dir / "ortho"
        ortho_dir.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ)
        apply_setting_env(env, args)
        env.update(
            {
                "LIVING_GAME_VIEW": models,
                "LIVING_GAME_VIEW_ENV": args.env_id,
                "LIVING_GAME_VIEW_ATMO": "1",
                "LIVING_GAME_DAY_MINUTES": "0",
                "LIVING_GAME_HOUR": "12.0",
                "LIVING_GAME_SIZE": args.size,
                "LIVING_GAME_VIEW_ORTHO": "1",
                "LIVING_GAME_VIEW_CLIP": args.clip or "bind",
                "LIVING_GAME_VIEW_SHOTS": "front,side",
                "LIVING_GAME_VIEW_OUT": str(ortho_dir),
                "RUST_LOG": os.environ.get("RUST_LOG", "warn,living_game=info"),
            }
        )
        print(f"lookdev_shoot: [characters/ortho] -> {ortho_dir}", flush=True)
        r = subprocess.run([str(bin_path)], cwd=REPO, env=env)
        if r.returncode != 0:
            sys.exit(f"lookdev_shoot: living-game exited {r.returncode} on characters/ortho")

    return {
        "models": models,
        "shots": shots,
        "times": {tag: hr for tag, hr in times},
        "sheets": sheets,
        "ortho": str(ortho_dir) if ortho_dir else None,
        "reports": reports,
    }


def parse_frames_csv(csv_path: Path, warmup_s: float, bench_s: float | None = None) -> dict:
    """Compute steady-state frame-time statistics matching survey baseline/frametime.json.

    `LIVING_GAME_FRAMES` starts recording at process startup (through loading and sync).
    When `bench_s` is given, take the steady-state window `[t_end - bench_s - tail, t_end - tail]`
    (excluding startup/warmup and the final dump/screenshot readback frames).
    """
    rows: list[tuple[int, float, float]] = []
    for line in csv_path.read_text().splitlines():
        parts = line.strip().split(",")
        if len(parts) != 3:
            continue
        try:
            t_us = int(parts[0])
            dt_ms = int(parts[1]) / 1000.0
            work_ms = int(parts[2]) / 1000.0
        except ValueError:
            continue
        rows.append((t_us, dt_ms, work_ms))
    if not rows:
        return {"frames": 0}
    t0 = rows[0][0]
    t_end = rows[-1][0]
    if bench_s is not None and (t_end - t0) > int((bench_s + 1.0) * 1_000_000):
        tail_us = 400_000  # exclude final dump/shot readback frames
        hi = t_end - tail_us
        lo = max(t0 + int(warmup_s * 1_000_000), hi - int(bench_s * 1_000_000))
        steady = [r for r in rows if lo <= r[0] <= hi]
    else:
        cutoff = t0 + int(warmup_s * 1_000_000)
        steady = [r for r in rows if r[0] >= cutoff]
    if not steady:
        steady = rows
    dts = sorted(r[1] for r in steady)
    works = sorted(r[2] for r in steady)
    n = len(dts)
    mean_ms = sum(dts) / n
    work_mean_ms = sum(works) / n

    def pct(xs: list[float], p: float) -> float:
        idx = min(len(xs) - 1, max(0, int(round((len(xs) - 1) * p))))
        return xs[idx]

    over = sum(1 for x in dts if x > 16.7)
    span_s = (steady[-1][0] - steady[0][0]) / 1_000_000.0 if n > 1 else 0.0
    target = 1000.0 / 60.0
    p99 = pct(dts, 0.99)
    return {
        "frames": n,
        "steady_span_s": round(span_s, 2),
        "mean_ms": round(mean_ms, 2),
        "fps": round(1000.0 / mean_ms, 1) if mean_ms > 0 else 0.0,
        "p50_ms": round(pct(dts, 0.50), 2),
        "p95_ms": round(pct(dts, 0.95), 2),
        "p99_ms": round(p99, 2),
        "max_ms": round(dts[-1], 2),
        "frames_over_16_7ms": over,
        "frames_over_16_7ms_pct": round(100.0 * over / n, 2),
        "headroom_mean_ms": round(target - mean_ms, 3),
        "headroom_p99_ms": round(target - p99, 3),
        "cpu_work_mean_ms": round(work_mean_ms, 2),
        "cpu_work_p99_ms": round(pct(works, 0.99), 2),
    }


def run_plaza(bin_path: Path, out_dir: Path, times: list[tuple[str, float]], args: argparse.Namespace) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    own_world = not args.run
    run_id = args.run or f"ui-lookdev-{time.strftime('%m%d-%H%M%S')}"
    drive_name = args.drive_name or ("plaza-bench" if args.bench else "plaza-lookdev")

    if own_world:
        print(f"lookdev_shoot: launching scratch Cullet world verify-{run_id}", flush=True)
        cmd = [sys.executable, str(VERIFY_PY), "launch", "--run", run_id, "--seed", "cullet"]
        if args.target_dir:
            cmd += ["--target-dir", args.target_dir]
        r = subprocess.run(cmd, cwd=REPO)
        if r.returncode != 0:
            sys.exit(f"lookdev_shoot: verify.py launch failed ({r.returncode})")

    try:
        env = dict(os.environ)
        apply_setting_env(env, args)
        ax, ay = PLAZA_ANCHOR
        sync_args: list[str] = []
        if args.bench:
            tag, hr = times[0]
            frames_csv = out_dir / "frames.csv"
            env["LIVING_GAME_FPS_CAP"] = "0"
            env["LIVING_GAME_FRAMES"] = str(frames_csv)
            sync_args.append(f"setup=place_at|{{me}}|{ax}|{ay};sql|UPDATE world SET epoch_ms = {{epoch_at:{hr:g}}} WHERE id = 0")
            plan = f"ready;frame:0;sync:setup;sync:scene;look:0;wait:{args.warmup_s + args.bench_s:g};dump:bench;shot:plaza_middle_{tag};quit"
        else:
            # Middle across all requested times, then Near across reversed times (exact LOOKDEV_SCENE.md flow).
            first_tag, first_hr = times[0]
            sync_args.append(f"setup=place_at|{{me}}|{ax}|{ay};sql|UPDATE world SET epoch_ms = {{epoch_at:{first_hr:g}}} WHERE id = 0")
            steps = ["ready", "frame:0", "sync:setup", "sync:scene", "look:0", "wait:3.0", f"dump:middle_{first_tag}", f"shot:plaza_middle_{first_tag}"]
            for idx, (tag, hr) in enumerate(times[1:], start=1):
                sname = f"m_{idx}_{tag}"
                sync_args.append(f"{sname}=sql|UPDATE world SET epoch_ms = {{epoch_at:{hr:g}}} WHERE id = 0")
                steps += [f"sync:{sname}", "wait:2.5", f"shot:plaza_middle_{tag}"]
            steps += ["notches:15", "wait:1.5"]
            rev = list(reversed(times))
            steps += [f"dump:near_{rev[0][0]}", f"shot:plaza_near_{rev[0][0]}"]
            for idx, (tag, hr) in enumerate(rev[1:], start=1):
                sname = f"n_{idx}_{tag}"
                sync_args.append(f"{sname}=sql|UPDATE world SET epoch_ms = {{epoch_at:{hr:g}}} WHERE id = 0")
                steps += [f"sync:{sname}", "wait:2.5", f"shot:plaza_near_{tag}"]
            steps.append("quit")
            plan = ";".join(steps)

        cmd = [
            sys.executable,
            str(DRIVE_PY),
            "--run",
            run_id,
            "--name",
            drive_name,
            "--size",
            args.size,
            "--client",
            str(bin_path),
            "--timeout",
            str(args.timeout),
        ]
        for p in PLAZA_CROWD:
            cmd += ["--place", p]
        for s in sync_args:
            cmd += ["--sync", s]
        cmd += ["--plan", plan]

        print(f"lookdev_shoot: [plaza] run={run_id} size={args.size} bench={args.bench}", flush=True)
        r = subprocess.run(cmd, cwd=REPO, env=env)
        if r.returncode != 0:
            sys.exit(f"lookdev_shoot: drive.py failed ({r.returncode})")

        ev_dir = REPO / ".local/living/verify" / run_id / "ui" / drive_name
        copied: list[str] = []
        for pat in ("*.png", "*.json", "client.log", "plan.txt"):
            for src in sorted(ev_dir.glob(pat)):
                dst = out_dir / src.name
                shutil.copy2(src, dst)
                copied.append(str(dst))

        result: dict[str, object] = {
            "run": run_id,
            "drive_name": drive_name,
            "evidence_dir": str(ev_dir),
            "files": copied,
        }

        if not args.bench and not args.no_sheet:
            grid = [
                [out_dir / f"plaza_middle_{tag}.png" for tag, _ in times],
                [out_dir / f"plaza_near_{tag}.png" for tag, _ in times],
            ]
            sheet_path = out_dir / "plaza_sheet.png"
            if stitch_grid(sheet_path, grid):
                result["sheet"] = str(sheet_path)
                print(f"lookdev_shoot: contact sheet -> {sheet_path}", flush=True)

        if args.bench:
            csv_path = out_dir / "frames.csv"
            stats = parse_frames_csv(csv_path, warmup_s=args.warmup_s, bench_s=args.bench_s)
            (out_dir / "frametime_summary.json").write_text(json.dumps(stats, indent=2) + "\n")
            result["frametime"] = stats
            print(
                f"lookdev_shoot: bench {args.size}: mean={stats.get('mean_ms')} ms "
                f"p99={stats.get('p99_ms')} ms >16.7ms={stats.get('frames_over_16_7ms')}/{stats.get('frames')} "
                f"({stats.get('frames_over_16_7ms_pct')}%) headroom={stats.get('headroom_mean_ms')} ms",
                flush=True,
            )

        return result
    finally:
        if own_world and not args.keep_world:
            print(f"lookdev_shoot: cleaning up scratch world verify-{run_id}", flush=True)
            subprocess.run([sys.executable, str(VERIFY_PY), "cleanup", "--run", run_id], cwd=REPO)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "--mode",
        choices=("characters", "plaza", "both"),
        default="characters",
        help="What to shoot: offline character stage (default), live Cullet plaza, or both.",
    )
    ap.add_argument(
        "--models",
        default=None,
        help="Comma-separated .glb paths, recipe:..., or look:... keys (default: 3 calibration Cullet looks).",
    )
    ap.add_argument(
        "--times",
        default="noon,dusk,night",
        help="Comma-separated time presets (noon, dusk, night) or numeric hours (default: noon,dusk,night).",
    )
    ap.add_argument(
        "--shots",
        default=None,
        help="Override LIVING_GAME_VIEW_SHOTS for character mode (default: 5 locked LOOKDEV_SCENE poses).",
    )
    ap.add_argument("--env-id", default="cullet", help="Environment id for character mode (default: cullet).")
    ap.add_argument("--clip", default=None, help="Optional LIVING_GAME_VIEW_CLIP override (e.g. bind).")
    ap.add_argument("--ortho", action="store_true", help="Also shoot orthographic measuring view (front,side).")
    ap.add_argument("--plate", action="store_true", help="Set LIVING_GAME_VIEW_PLATE=1 in character mode.")
    ap.add_argument("--size", default="1920x1080", help="Output resolution WxH (default: 1920x1080).")
    ap.add_argument(
        "--out",
        default=None,
        help="Output directory (default: .local/living/lookdev/shots/<timestamp>).",
    )
    ap.add_argument("--bin", dest="bin_path", default=None, help="Path to release living-game binary.")
    ap.add_argument("--no-sheet", action="store_true", help="Skip stitching Pillow contact sheets.")

    # Look, quality, and render-scale settings (also honour LIVING_GAME_* env vars when omitted).
    ap.add_argument("--quality", choices=("low", "medium", "high"), default=None, help="LIVING_GAME_QUALITY.")
    ap.add_argument(
        "--render-scale",
        choices=("67", "75", "85", "100", "auto"),
        default=None,
        help="LIVING_GAME_RENDER_SCALE.",
    )
    ap.add_argument("--film", choices=("soft", "screen", "off"), default=None, help="LIVING_GAME_FILM.")
    ap.add_argument("--hair-shine", choices=("crown", "soft", "today"), default=None, help="LIVING_GAME_HAIR_SHINE.")
    ap.add_argument("--weather", choices=("clear", "rain", "fog", "storm"), default=None, help="LIVING_GAME_WEATHER (default: clear).")
    ap.add_argument("--look", default=None, help="LIVING_GAME_LOOK (look preset, for Step 1+).")
    ap.add_argument("--perf", default=None, help="LIVING_GAME_PERF comma flags (e.g. shadowfilter=hw,bloom=half).")
    ap.add_argument("--env", action="append", default=[], help="Extra KEY=VALUE env var (repeatable).")

    # Live Cullet plaza options.
    ap.add_argument("--run", default=None, help="Reuse an existing verify-ui-* run instead of launching/cleaning one.")
    ap.add_argument("--drive-name", default=None, help="Name of the drive.py evidence subfolder.")
    ap.add_argument("--keep-world", action="store_true", help="Do not clean up a scratch world launched by this tool.")
    ap.add_argument("--target-dir", default=None, help="Optional --target-dir passed to verify.py launch.")
    ap.add_argument("--timeout", type=float, default=600.0, help="drive.py timeout in seconds (default: 600).")
    ap.add_argument("--bench", action="store_true", help="Plaza mode: uncapped steady-state frame-time run (first --times entry).")
    ap.add_argument("--warmup-s", type=float, default=3.5, help="Benchmark warmup seconds excluded from stats (default: 3.5).")
    ap.add_argument("--bench-s", type=float, default=12.0, help="Benchmark steady-state duration in seconds (default: 12.0).")
    return ap


def main() -> None:
    args = build_parser().parse_args()
    bin_path = resolve_binary(args.bin_path)
    times = [parse_time_token(t) for t in args.times.split(",") if t.strip()]
    if not times:
        sys.exit("lookdev_shoot: --times must name at least one time preset or hour")

    out_dir = Path(args.out).expanduser() if args.out else REPO / ".local/living/lookdev/shots" / time.strftime("%Y%m%d-%H%M%S")
    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    # Snapshot effective LIVING_GAME_* environment for manifest reproducibility.
    effective_env = dict(os.environ)
    apply_setting_env(effective_env, args)
    tracked_env = {k: v for k, v in sorted(effective_env.items()) if k.startswith(("LIVING_GAME_", "LIVING_SIGHT_"))}

    manifest: dict[str, object] = {
        "schema_version": 1,
        "captured_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "git": git_info(),
        "host": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "platform": platform.platform(),
        },
        "binary": {
            "path": str(bin_path),
            "mtime": dt.datetime.fromtimestamp(bin_path.stat().st_mtime).astimezone().isoformat(timespec="seconds"),
        },
        "mode": args.mode,
        "size": args.size,
        "settings": tracked_env,
    }

    if args.mode == "characters":
        manifest["characters"] = run_characters(bin_path, out_dir, times, args)
    elif args.mode == "plaza":
        manifest["plaza"] = run_plaza(bin_path, out_dir, times, args)
    else:
        manifest["characters"] = run_characters(bin_path, out_dir / "characters", times, args)
        manifest["plaza"] = run_plaza(bin_path, out_dir / "plaza", times, args)

    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"lookdev_shoot: manifest -> {manifest_path}", flush=True)


if __name__ == "__main__":
    main()
