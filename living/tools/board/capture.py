"""Photograph models through the game's own renderer (the asset view, living/game/src/view.rs) in
the board's fixed shots: the same cameras, sizes and hours every time.

Generalised from living/tools/view_assets.sh (the batch asset view) and the character spike's
capture.sh (stills, held clip frames). One game process takes one group of shots (one image size
and one hour) of every member at once; clip frames are taken per member, since clip lengths
differ.
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
    # for anything that glows. The environment's day curve lights them (LIVING_GAME_VIEW_ATMO).
    "building": {
        "env": "cullet",
        "hours": {"day": 15.0, "night": 22.0},
        "groups": [
            {"size": "1280x960", "hour": "day", "shots": [("front", "0:8:1"), ("three-quarter", "40:18:1"), ("side", "90:8:1"), ("back", "180:8:1"), ("close", "30:10:0.45:0.3")]},
            {"size": "1600x900", "hour": "day", "shots": [("game", "game")]},
            {"size": "1280x960", "hour": "night", "glow": True, "shots": [("night-three-quarter", "40:18:1")]},
            {"size": "1600x900", "hour": "night", "glow": True, "shots": [("night-game", "game")]},
        ],
    },
    # Characters: the spike's stills (capture.sh), so its photographs compare with every later pass.
    "character": {
        "env": "",
        "hours": {"day": 15.0},
        "groups": [
            {"size": "1000x1000", "hour": "day", "shots": [
                ("front", "idle@1.0/0:8:0.62"), ("three-quarter", "idle@1.0/40:14:0.62"), ("side", "idle@1.0/90:8:0.62"), ("back", "idle@1.0/180:8:0.62"),
                ("face", "idle@1.0/0:4:0.2:0.92"), ("face-three-quarter", "idle@1.0/40:6:0.2:0.92"), ("face-side", "idle@1.0/90:4:0.2:0.92"),
                ("hands", "talk@2.0/35:10:0.3:0.62"), ("sit-three-quarter", "sit_idle@1.0/40:14:0.62"), ("sit-side", "sit_idle@1.0/90:8:0.62"),
                ("elbow", "sword_slash@1.25/35:10:0.34:0.72"), ("knee", "run@0.2/90:6:0.34:0.3"), ("shoulder", "wave@1.4/20:8:0.34:0.82"), ("hip", "sit_idle@1.0/60:20:0.4:0.45")]},
            {"size": "1600x900", "hour": "day", "crop": True, "shots": [("game", "idle@1.0/game"), ("game-walk", "walk@0.3/game")]},
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


def preset_hash(preset):
    return hashlib.sha256(json.dumps(preset, sort_keys=True).encode()).hexdigest()[:8]


def git(repo, *args):
    r = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else ""


def renderer_identity(repo, preset):
    """Which renderer took the photographs: the game's commit, and a hash of uncommitted changes
    to the game, so two captures can be told comparable or not."""
    commit = git(repo, "rev-parse", "HEAD")
    diff = git(repo, "diff", "HEAD", "--", "living/game/src", "living/game/assets/envs", "living/game/Cargo.toml")
    key = commit[:8] + ("+" + hashlib.sha256(diff.encode()).hexdigest()[:6] if diff else "")
    return {"method": "asset-view", "commit": commit, "dirty": bool(diff), "key": key, "env": preset.get("env", ""), "hours": preset["hours"], "preset": preset_hash(preset)}


def build_game(repo, target_dir=None, jobs=12):
    """Build the game (release) and return the binary's path."""
    target = target_dir or os.environ.get("CARGO_TARGET_DIR") or next((t for t in (os.path.join(repo, ".local", "target"),) if os.path.isdir(t)), os.path.join(repo, ".local", "board-target"))
    target = os.path.abspath(target)
    env = {**os.environ, "CARGO_TARGET_DIR": target}
    key = (repo, target)
    if key in _BUILT:
        return _BUILT[key]
    print(f"board: building the game in {repo} (target {target})", file=sys.stderr)
    r = subprocess.run(["cargo", "build", "--release", "-q", "-j", str(jobs), "-p", "living-game", "--manifest-path", os.path.join(repo, "living", "Cargo.toml")], env=env, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stderr[-4000:], file=sys.stderr)
        sys.exit("board: the game did not build")
    _BUILT[key] = os.path.join(target, "release", "living-game")
    return _BUILT[key]


_BUILT = {}


def _view(game, tokens, shots, out, size, env_id, hour, day_curve=True):
    """One batch run of the asset view. Returns {token stem: [png paths in shot order]}."""
    os.makedirs(out, exist_ok=True)
    env = {**os.environ, "LIVING_GAME_VIEW": ",".join(tokens), "LIVING_GAME_VIEW_OUT": out, "LIVING_GAME_VIEW_ENV": env_id or "",
           "LIVING_GAME_VIEW_SHOTS": ",".join(shots), "LIVING_GAME_SIZE": size, "LIVING_GAME_HOUR": str(hour),
           "RUST_LOG": os.environ.get("RUST_LOG", "warn,living_game=info")}
    if day_curve:
        env["LIVING_GAME_VIEW_ATMO"] = "1"
    env.pop("LIVING_GAME_VIEW_HEIGHT", None)
    r = subprocess.run([game], env=env, capture_output=True, text=True)
    log = r.stdout + r.stderr
    bad = [l for l in log.splitlines() if re.search(r"ERROR|panicked|did not load|no recipe|no environment", l)]
    if r.returncode != 0 or bad:
        print("\n".join(bad[-8:]) or log[-1500:], file=sys.stderr)
    if r.returncode != 0:
        sys.exit(f"board: the asset view failed (exit {r.returncode})")
    found = {}
    for t in tokens:
        stem = os.path.splitext(os.path.basename(t))[0] if not t.startswith("recipe:") else t
        d = os.path.join(out, stem)
        pngs = [f for f in os.listdir(d) if re.match(r"\d+-.*\.png$", f)] if os.path.isdir(d) else []
        found[t] = [os.path.join(d, f) for f in sorted(pngs, key=lambda f: int(f.split("-", 1)[0]))]
        rep = os.path.join(d, "report.json")
        found[t + "#report"] = json.load(open(rep)) if os.path.exists(rep) else None
    return found


def _save(src, dst, crop=False):
    from PIL import Image

    im = Image.open(src).convert("RGB")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    im.save(dst, quality=92)
    if crop:
        # A character at the game camera is a few dozen pixels tall: the frame's middle, four times.
        w, h = im.size
        im.crop((w // 2 - 100, h // 2 - 75, w // 2 + 100, h // 2 + 75)).resize((800, 600), Image.NEAREST).save(dst[:-4] + "-crop.png")


def clip_seconds(repo, token, clip):
    """A clip's length from the animated file's `.clips.json` (characters)."""
    base = None
    if token.startswith("recipe:"):
        name = token.split(":", 1)[1]
        book = json.load(open(os.path.join(repo, "living", "game", "assets", "characters", "recipes.json")))
        base = next((r["base"] for r in book["recipes"] if r["name"] == name), None)
        base = base and os.path.splitext(os.path.basename(base))[0]
    else:
        base = os.path.splitext(os.path.basename(token))[0]
    for d in (os.path.join(repo, "living", "game", "assets", "lookdev", "anim"), os.path.dirname(token) if not token.startswith("recipe:") else ""):
        p = os.path.join(d, f"{base}.clips.json") if d else ""
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
    """Photograph `members` ([{"name", "token", "glow"}]) into out/<member>/<shot>.jpg and
    out/<member>/clips/<clip>-<view>.mp4. Returns ({member: [shot names]}, {member: [clip
    records]}, {member: view report})."""
    preset = PRESETS[preset_name]
    hours = preset["hours"]
    shots_by_member, clips_by_member, reports = {m["name"]: [] for m in members}, {m["name"]: [] for m in members}, {}
    for gi, group in enumerate(preset["groups"]):
        who = [m for m in members if m.get("glow") or not group.get("glow")]
        shots = [s for s in group["shots"] if not only_shots or s[0] in only_shots]
        if not who or not shots:
            continue
        tmp = os.path.join(scratch, f"g{gi}")
        shutil.rmtree(tmp, ignore_errors=True)
        found = _view(game, [m["token"] for m in who], [s[1] for s in shots], tmp, group["size"], preset.get("env", ""), hours[group["hour"]])
        for m in who:
            pngs = found.get(m["token"], [])
            if found.get(m["token"] + "#report") and m["name"] not in reports:
                reports[m["name"]] = found[m["token"] + "#report"]
            if len(pngs) != len(shots):
                print(f"board: {m['name']}: {len(pngs)} photographs for {len(shots)} shots in group {gi}", file=sys.stderr)
            for (name, _), png in zip(shots, pngs):
                _save(png, os.path.join(out, m["name"], f"{name}.jpg"), crop=group.get("crop", False))
                shots_by_member[m["name"]].append(name)
        shutil.rmtree(tmp, ignore_errors=True)
    if clips and preset.get("clips"):
        for m in members:
            for clip, view, spec, t0, t1, fps in preset["clips"]:
                if clips is not True and f"{clip}-{view}" not in clips:
                    continue
                end = t1 if t1 is not None else clip_seconds(repo, m["token"], clip)
                if not end:
                    continue
                n = max(1, round((end - t0) * fps))
                specs = [f"{clip}@{t0 + k / fps:.3f}/{spec}" for k in range(n)]
                tmp = os.path.join(scratch, f"c-{m['name']}-{clip}-{view}")
                shutil.rmtree(tmp, ignore_errors=True)
                found = _view(game, [m["token"]], specs, tmp, preset.get("clip_size", "720x720"), preset.get("env", ""), hours["day"])
                frames = os.path.join(tmp, "frames")
                os.makedirs(frames, exist_ok=True)
                for k, png in enumerate(found.get(m["token"], [])):
                    os.replace(png, os.path.join(frames, f"{k:03d}.png"))
                loop = preset.get("loops", {}).get(clip, 1)
                dst = os.path.join(out, m["name"], "clips", f"{clip}-{view}.mp4")
                if encode(frames, dst, fps, loop):
                    clips_by_member[m["name"]].append({"name": f"{clip}-{view}", "file": f"clips/{clip}-{view}.mp4", "frames": n, "fps": fps, "loop": loop})
                shutil.rmtree(tmp, ignore_errors=True)
    return shots_by_member, clips_by_member, reports
