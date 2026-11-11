"""Photograph models through the game's own renderer (the asset view, living/game/src/view.rs) in
the board's fixed shots: the same cameras, sizes, hours and weather every time.

Generalised from living/tools/view_assets.sh (the batch asset view) and the character spike's
capture.sh (stills, held clip frames). One game process takes one group of shots (one image size
and one hour) of every member at once; clip frames are taken per member, since clip lengths
differ. Photographs are matched to shots by the names the view gives them, never by position.
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys

# A shot is (name, view spec). View specs are the asset view's: `front`, `game`,
# `YAW:PITCH[:ZOOM[:AIM]]`, `<clip>@<seconds>/<view>`.
PRESETS = {
    # Buildings and props: the four views, a close look at the base, the game camera, and night
    # for anything that glows, lit by the environment's day curve (LIVING_GAME_VIEW_ATMO).
    "building": {
        "env": "cullet",
        "day_curve": True,
        "weather": "clear",
        "hours": {"day": 15.0, "night": 22.0},
        "groups": [
            {"size": "1280x960", "hour": "day", "shots": [("front", "0:8:1"), ("three-quarter", "40:18:1"), ("side", "90:8:1"), ("back", "180:8:1"), ("close", "30:10:0.45:0.3")]},
            {"size": "1600x900", "hour": "day", "shots": [("game", "game")]},
            {"size": "1280x960", "hour": "night", "glow": True, "shots": [("night-three-quarter", "40:18:1")]},
            {"size": "1600x900", "hour": "night", "glow": True, "shots": [("night-game", "game")]},
        ],
    },
    # Characters: the spike's stills and clips (capture.sh) in its light (the look-dev mood, the
    # sun at 15:00, no day curve), so its photographs compare with every later pass.
    "character": {
        "env": "",
        "day_curve": False,
        "weather": "clear",
        "hours": {"day": 15.0},
        "groups": [
            {"size": "1000x1000", "hour": "day", "shots": [
                ("front", "idle@1.0/0:8:0.62"), ("three-quarter", "idle@1.0/40:14:0.62"), ("side", "idle@1.0/90:8:0.62"), ("back", "idle@1.0/180:8:0.62"),
                ("face", "idle@1.0/0:4:0.2:0.92"), ("face-three-quarter", "idle@1.0/40:6:0.2:0.92"), ("face-side", "idle@1.0/90:4:0.2:0.92"),
                ("hands", "talk@2.0/35:10:0.3:0.62"), ("sit-three-quarter", "sit_idle@1.0/40:14:0.62"), ("sit-side", "sit_idle@1.0/90:8:0.62")]},
            {"size": "1600x900", "hour": "day", "crop": True, "shots": [("game", "idle@1.0/game"), ("game-walk", "walk@0.3/game")]},
            {"size": "1000x1000", "hour": "day", "shots": [
                ("elbow", "sword_slash@1.25/35:10:0.34:0.72"), ("knee", "run@0.2/90:6:0.34:0.3"), ("shoulder", "wave@1.4/20:8:0.34:0.82"), ("hip", "sit_idle@1.0/60:20:0.4:0.45")]},
        ],
        # (clip, view name, view spec, start s, end s or None for the clip's length, fps)
        "clips": [("idle", "tq", "40:14:0.74", 0, 4, 12), ("walk", "tq", "40:14:0.74", 0, None, 15), ("walk", "side", "90:8:0.74", 0, None, 15),
                  ("run", "tq", "40:14:0.74", 0, None, 24), ("run", "side", "90:8:0.74", 0, None, 24), ("sword_slash", "tq", "40:14:0.74", 0, None, 15),
                  ("sit_down", "tq", "40:14:0.74", 0, None, 15), ("sit_idle", "tq", "40:14:0.74", 0, 2, 12)],
        "clip_size": "720x720",
        "loops": {"walk": 4, "run": 6},
    },
}
PRESETS["prop"] = PRESETS["building"]
ANGLES = {"front", "three-quarter", "side", "back", "above", "game"}


def preset_hash(preset):
    return hashlib.sha256(json.dumps(preset, sort_keys=True).encode()).hexdigest()[:8]


def git(repo, *args):
    r = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else ""


GAME_PATHS = ["living/game/src", "living/game/assets/envs", "living/game/Cargo.toml", "living/Cargo.lock"]


def renderer_identity(repo, preset, game=None):
    """Which renderer took the photographs: the game's commit, and a hash of uncommitted changes
    to the game (sources, environments, dependencies), so two captures can be told comparable or
    not. A binary given from elsewhere (--game) is keyed by its own hash."""
    commit = git(repo, "rev-parse", "HEAD")
    diff = git(repo, "diff", "HEAD", "--", *GAME_PATHS) + git(repo, "ls-files", "--others", "--exclude-standard", "--", "living/game/src")
    key = commit[:8] + ("+" + hashlib.sha256(diff.encode()).hexdigest()[:6] if diff else "")
    ident = {"method": "asset-view", "commit": commit, "dirty": bool(diff), "key": key, "env": preset.get("env", ""), "hours": preset["hours"],
             "weather": preset.get("weather", ""), "day_curve": preset.get("day_curve", False), "preset": preset_hash(preset)}
    if game:
        h = hashlib.sha256(open(game, "rb").read()).hexdigest()[:8]
        ident.update(key=f"bin:{h}", binary=os.path.abspath(game), commit_assumed=commit)
    return ident


def target_dir(repo, publishing_repo):
    """Where the renderer's game is built: CARGO_TARGET_DIR only when the renderer is the
    publishing repository (else a track's own binary would be overwritten by another tree's
    game); otherwise the renderer repository's .local/target, or .local/board-target."""
    inherited = os.environ.get("CARGO_TARGET_DIR")
    if inherited and os.path.abspath(repo) == os.path.abspath(publishing_repo):
        return os.path.abspath(inherited)
    own = os.path.join(repo, ".local", "target")
    return own if os.path.isdir(own) else os.path.join(repo, ".local", "board-target")


_BUILT = {}


def build_game(repo, publishing_repo, jobs=12):
    """Build the game (release) and return the binary's path."""
    target = target_dir(repo, publishing_repo)
    if (repo, target) in _BUILT:
        return _BUILT[(repo, target)]
    print(f"board: building the game of {repo} in {target} (-j {jobs})", file=sys.stderr)
    env = {**os.environ, "CARGO_TARGET_DIR": target}
    r = subprocess.run(["cargo", "build", "--release", "-q", "-j", str(jobs), "-p", "living-game", "--manifest-path", os.path.join(repo, "living", "Cargo.toml")],
                       env=env, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stderr[-4000:], file=sys.stderr)
        sys.exit("board: the game did not build")
    _BUILT[(repo, target)] = os.path.join(target, "release", "living-game")
    return _BUILT[(repo, target)]


def f32(x):
    """A number as Rust prints an f32 (shortest round trip): 1.0 -> 1, 0.300 -> 0.3."""
    import numpy as np

    return np.format_float_positional(np.float32(x), trim="-")


def shot_name(spec):
    """The name the asset view gives a spec's photograph (view.rs parse_shots, parse_view)."""
    def view(v):
        return v if v in ANGLES else v.replace(":", "_")

    if spec in ANGLES or re.fullmatch(r"[-\d.]+(:[-\d.]+)+", spec):
        return view(spec)
    clip, _, v = spec.partition("/")
    cname, _, at = clip.partition("@")
    cname = re.sub(r"[^A-Za-z0-9_-]", "_", cname)
    return f"clip-{cname}@{f32(float(at))}" + (f"-{view(v)}" if v else "")


def _env(base):
    """The caller's environment without any game settings: the board's shots set their own."""
    return {k: v for k, v in base.items() if not k.startswith(("LIVING_GAME_", "LIVING_SIGHT_", "LIVING_PERF"))}


def _view(game, tokens, specs, out, size, preset, hour):
    """One batch run of the asset view. Returns ({token: [png or None per spec]}, {token: report})."""
    os.makedirs(out, exist_ok=True)
    env = {**_env(os.environ), "LIVING_GAME_VIEW": ",".join(tokens), "LIVING_GAME_VIEW_OUT": out, "LIVING_GAME_VIEW_ENV": preset.get("env", ""),
           "LIVING_GAME_VIEW_SHOTS": ",".join(specs), "LIVING_GAME_SIZE": size, "LIVING_GAME_HOUR": str(hour), "LIVING_GAME_DAY_MINUTES": "0",
           "RUST_LOG": "warn,living_game=info"}
    if preset.get("weather"):
        env["LIVING_GAME_WEATHER"] = preset["weather"]
    if preset.get("day_curve"):
        env["LIVING_GAME_VIEW_ATMO"] = "1"
    r = subprocess.run([game], env=env, capture_output=True, text=True)
    log = r.stdout + r.stderr
    bad = [l for l in log.splitlines() if re.search(r"ERROR|panicked|did not load|no recipe|no environment|no clip or view|bad view", l)]
    if bad:
        print("\n".join(bad[-8:]), file=sys.stderr)
    if r.returncode != 0:
        print(log[-1500:], file=sys.stderr)
        sys.exit(f"board: the asset view failed (exit {r.returncode})")
    found, reports = {}, {}
    want = [shot_name(s) for s in specs]
    for t in tokens:
        stem = t if t.startswith("recipe:") else os.path.splitext(os.path.basename(t))[0]
        d = os.path.join(out, stem)
        files = sorted((f for f in (os.listdir(d) if os.path.isdir(d) else []) if re.match(r"\d+-.*\.png$", f)), key=lambda f: int(f.split("-", 1)[0]))
        queues = {}
        for f in files:
            queues.setdefault(f.split("-", 1)[1][:-4], []).append(os.path.join(d, f))
        found[t] = [queues[n].pop(0) if queues.get(n) else None for n in want]
        rep = os.path.join(d, "report.json")
        reports[t] = json.load(open(rep)) if os.path.exists(rep) else None
    return found, reports


def _save(src, dst, crop=False):
    from PIL import Image

    im = Image.open(src).convert("RGB")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    im.save(dst, quality=92)
    if crop:
        # A character at the game camera is a few dozen pixels tall: the frame's middle, four times.
        w, h = im.size
        im.crop((w // 2 - 100, h // 2 - 75, w // 2 + 100, h // 2 + 75)).resize((800, 600), Image.NEAREST).save(dst[:-4] + "-crop.png")


def clip_seconds(repo, member, clip, report):
    """A clip's length: from the view's own report of the file, else the animated file's
    `.clips.json` (characters)."""
    for c in (report or {}).get("clips", []):
        if c.get("name") == clip and c.get("seconds"):
            return c["seconds"]
    token = member["token"]
    p = None
    if token.startswith("recipe:"):
        book_path = os.path.join(repo, "living", "game", "assets", "characters", "recipes.json")
        book = json.load(open(book_path)) if os.path.exists(book_path) else {"recipes": []}
        base = next((r["base"] for r in book["recipes"] if r["name"] == token.split(":", 1)[1]), None)
        stem = base and os.path.splitext(os.path.basename(base))[0]
        p = stem and os.path.join(repo, "living", "game", "assets", "lookdev", "anim", f"{stem}.clips.json")
    else:
        p = os.path.splitext(member.get("source") or token)[0] + ".clips.json"
    if p and os.path.exists(p):
        c = json.load(open(p)).get(clip)
        return c and c.get("seconds")
    return None


def encode(frames_dir, out, fps, loop=1):
    """Frames NNN.png to an H.264 mp4 (libx264 where present, else OpenH264)."""
    n = len([f for f in os.listdir(frames_dir) if f.endswith(".png")])
    if not n:
        return False
    enc = "libx264" if "libx264" in subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True).stdout else "libopenh264"
    filt = f"loop=loop={loop - 1}:size={n}:start=0,format=yuv420p"
    os.makedirs(os.path.dirname(out), exist_ok=True)
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(fps), "-i", os.path.join(frames_dir, "%03d.png"), "-frames:v", str(n * loop), "-vf", filt,
                        "-c:v", enc, "-b:v", "2500k", "-movflags", "+faststart", out], capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stderr[-600:], file=sys.stderr)
    return r.returncode == 0


def capture(game, repo, members, preset_name, out, scratch, clips=True, only_shots=None):
    """Photograph `members` ([{"name", "token", "glow", "source"?, "clips"?: False}]) into
    out/<member>/<shot>.jpg and out/<member>/clips/<clip>-<view>.mp4. Returns
    (shots {member: [names]}, clips {member: [records]}, view reports {member: report},
    missing {member: [shots not photographed]})."""
    preset = PRESETS[preset_name]
    hours = preset["hours"]
    shots_by, clips_by, reports, missing = ({m["name"]: [] for m in members} for _ in range(4))
    for gi, group in enumerate(preset["groups"]):
        who = [m for m in members if m.get("glow") or not group.get("glow")]
        shots = [s for s in group["shots"] if not only_shots or s[0] in only_shots]
        if not who or not shots:
            continue
        tmp = os.path.join(scratch, f"g{gi}")
        shutil.rmtree(tmp, ignore_errors=True)
        found, reps = _view(game, [m["token"] for m in who], [s[1] for s in shots], tmp, group["size"], preset, hours[group["hour"]])
        for m in who:
            if reps.get(m["token"]) and not isinstance(reports[m["name"]], dict):
                reports[m["name"]] = reps[m["token"]]
            for (name, _), png in zip(shots, found.get(m["token"]) or [None] * len(shots)):
                if png:
                    _save(png, os.path.join(out, m["name"], f"{name}.jpg"), crop=group.get("crop", False))
                    shots_by[m["name"]].append(name)
                else:
                    missing[m["name"]].append(name)
        shutil.rmtree(tmp, ignore_errors=True)
    if clips and preset.get("clips"):
        for m in members:
            if m.get("clips") is False:
                continue
            for clip, view, spec, t0, t1, fps in preset["clips"]:
                if clips is not True and f"{clip}-{view}" not in clips:
                    continue
                end = t1 if t1 is not None else clip_seconds(repo, m, clip, reports.get(m["name"]))
                if not end:
                    print(f"board: {m['name']}: no clip {clip}; skipped", file=sys.stderr)
                    continue
                n = max(1, round((end - t0) * fps))
                specs = [f"{clip}@{t0 + k / fps:.3f}/{spec}" for k in range(n)]
                tmp = os.path.join(scratch, f"c-{m['name']}-{clip}-{view}")
                shutil.rmtree(tmp, ignore_errors=True)
                found, _ = _view(game, [m["token"]], specs, tmp, preset.get("clip_size", "720x720"), preset, hours["day"])
                frames = os.path.join(tmp, "frames")
                os.makedirs(frames, exist_ok=True)
                got = [p for p in found.get(m["token"]) or [] if p]
                for k, png in enumerate(got):
                    os.replace(png, os.path.join(frames, f"{k:03d}.png"))
                if len(got) < n:
                    print(f"board: {m['name']}: clip {clip}-{view} has {len(got)} of {n} frames", file=sys.stderr)
                    missing[m["name"]].append(f"clip {clip}-{view}")
                loop = preset.get("loops", {}).get(clip, 1)
                dst = os.path.join(out, m["name"], "clips", f"{clip}-{view}.mp4")
                if got and encode(frames, dst, fps, loop):
                    clips_by[m["name"]].append({"name": f"{clip}-{view}", "file": f"clips/{clip}-{view}.mp4", "frames": len(got), "fps": fps, "loop": loop})
                shutil.rmtree(tmp, ignore_errors=True)
    return shots_by, clips_by, {k: v for k, v in reports.items() if isinstance(v, dict)}, {k: v for k, v in missing.items() if v}
