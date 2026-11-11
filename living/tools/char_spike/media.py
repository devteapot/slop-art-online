#!/usr/bin/env python3
"""Spike (branch char-spike): turn capture.sh's frames into the comparison page's media.

    python3 living/tools/char_spike/media.py CAPTURE_DIR PAGE_DIR [CAST_DIR]

CAPTURE_DIR holds one folder per character (`ours`, `vroid`, `vroid-smith`, and optional
variants) as capture.sh writes them. PAGE_DIR gets:
- `img/<character>-<shot>.jpg`: the stills;
- `img/game-<character>.png`: the game-camera frame's middle, enlarged four times without
  smoothing, since a character is only a few dozen pixels tall there;
- `clips/<clip>-<view>.mp4`: ours beside the VRoid control, the same frames at the same times;
- `img/cast-lineup.jpg`, `img/cast-faces.jpg` and `cast.json` from cast.py's CAST_DIR, if given;
- `stats.json`: what each character file holds (triangles by part, bones, materials, textures,
  morph targets, spring groups, bytes).
Needs Pillow and ffmpeg.
"""

import json
import os
import struct
import subprocess
import sys

from PIL import Image

REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
ANIM = os.path.join(REPO, "living", "game", "assets", "lookdev", "anim")
FILES = {"ours": "own-man", "vroid": "vroid-Sendagaya_Shino", "elder": "own-elder", "woman": "own-woman", "youth": "own-youth"}
CLIPS = [("idle", "tq", 12), ("walk", "tq", 15), ("walk", "side", 15), ("run", "tq", 24), ("run", "side", 24), ("sword_slash", "tq", 15), ("sit_down", "tq", 15), ("sit_idle", "tq", 12)]
LOOPS = {"walk": 4, "run": 6}


def glb_stats(path):
    b = open(path, "rb").read()
    jl = struct.unpack("<I", b[12:16])[0]
    j = json.loads(b[20 : 20 + jl])
    acc = j["accessors"]
    parts = {}
    for n in j["nodes"]:
        if "mesh" not in n:
            continue
        m = j["meshes"][n["mesh"]]
        t = sum((acc[p["indices"]]["count"] if "indices" in p else acc[p["attributes"]["POSITION"]]["count"]) // 3 for p in m["primitives"])
        parts[n.get("name", "?")] = parts.get(n.get("name", "?"), 0) + t
    verts = 0
    seen = set()
    for m in j["meshes"]:
        for p in m["primitives"]:
            a = p["attributes"]["POSITION"]
            if a not in seen:
                seen.add(a)
                verts += acc[a]["count"]
    images = j.get("images", [])
    img_bytes = sum(j["bufferViews"][i["bufferView"]]["byteLength"] for i in images if "bufferView" in i)
    names = [n.get("name", "") for n in j["nodes"]]
    vrm = j.get("extensions", {}).get("VRM", {})
    return dict(
        file=os.path.basename(path), bytes=len(b), triangles=sum(parts.values()), vertices=verts, parts=parts,
        nodes=len(names), bip_bones=sum(1 for n in names if n.startswith("J_Bip") and not n.endswith("_end")),
        spring_bones=sum(1 for n in names if n.startswith("J_Sec")), skin_joints=max((len(s["joints"]) for s in j.get("skins", [])), default=0),
        materials=[m.get("name") for m in j.get("materials", [])], textures=len(images), texture_bytes=img_bytes,
        morph_targets=max((len(p.get("targets", [])) for m in j["meshes"] for p in m["primitives"]), default=0),
        spring_groups=len(vrm.get("secondaryAnimation", {}).get("boneGroups", [])),
        vertex_colours=all("COLOR_0" in p["attributes"] for m in j["meshes"] for p in m["primitives"]),
        clips=[a.get("name") for a in j.get("animations", [])],
    )


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"{' '.join(cmd[:6])}…\n{r.stderr[-800:]}")


def main():
    cap, page = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
    os.makedirs(os.path.join(page, "img"), exist_ok=True)
    os.makedirs(os.path.join(page, "clips"), exist_ok=True)
    chars = sorted(d for d in os.listdir(cap) if os.path.isdir(os.path.join(cap, d, "stills")))
    for c in chars:
        d = os.path.join(cap, c, "stills")
        for f in sorted(os.listdir(d)):
            im = Image.open(os.path.join(d, f)).convert("RGB")
            name = f[:-4]
            if name.startswith("game"):
                w, h = im.size
                # The camera looks at the character's middle: the frame's centre.
                box = (w // 2 - 100, h // 2 - 75, w // 2 + 100, h // 2 + 75)
                im.crop(box).resize((800, 600), Image.NEAREST).save(os.path.join(page, "img", f"{c}-{name}-crop.png"))
                im.save(os.path.join(page, "img", f"{c}-{name}.jpg"), quality=90)
            else:
                im.save(os.path.join(page, "img", f"{c}-{name}.jpg"), quality=90)
    # A blink and an open mouth among the face frames taken while the game animates the face:
    # the fewest eye-white pixels, and the most dark mouth pixels.
    for c in chars:
        d = os.path.join(cap, c, "blink")
        if not os.path.isdir(d):
            continue
        import numpy as np

        seen = []
        for f in sorted(os.listdir(d)):
            im = Image.open(os.path.join(d, f)).convert("RGB")
            px = np.asarray(im).astype(int)[150:450, 150:450]
            r, g, b = px[..., 0], px[..., 1], px[..., 2]
            white = int(((r > 185) & (g > 185) & (b > 180) & (abs(r - b) < 25)).sum())
            mouth = int(((r < 125) & (r > 50) & (g < 75) & (b < 75) & (r > g + 15)).sum())
            seen.append((white, mouth, im))
        picks = {"shut": min(seen, key=lambda x: x[0]), "open": min(seen, key=lambda x: (x[1], -x[0])), "mouth-open": max(seen, key=lambda x: x[1])}
        picks["blink-shut"], picks["blink-open"] = picks.pop("shut"), picks.pop("open")
        for k, x in picks.items():
            x[2].save(os.path.join(page, "img", f"{c}-{k}.jpg"), quality=92)
        print(f"blink {c}: eye-white pixels {picks['blink-shut'][0]} shut, {picks['blink-open'][0]} open; mouth pixels {picks['mouth-open'][1]} open")
    # Clips: ours beside the control.
    if all(os.path.isdir(os.path.join(cap, c, "frames")) for c in ("ours", "vroid")):
        for clip, view, fps in CLIPS:
            a, b = (os.path.join(cap, c, "frames", f"{clip}-{view}") for c in ("ours", "vroid"))
            n = min(len(os.listdir(a)), len(os.listdir(b)))
            loop = LOOPS.get(clip, 1)
            out = os.path.join(page, "clips", f"{clip}-{view}.mp4")
            filt = f"[0:v][1:v]hstack=inputs=2,loop=loop={loop - 1}:size={n}:start=0,format=yuv420p[v]"
            run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(fps), "-i", os.path.join(a, "%03d.png"), "-framerate", str(fps), "-i", os.path.join(b, "%03d.png"),
                 "-frames:v", str(n * loop), "-filter_complex", filt, "-map", "[v]", "-c:v", "libopenh264", "-b:v", "3500k", "-movflags", "+faststart", out])
            print(f"clip {out}: {n} frames x{loop} at {fps} fps")
    if len(sys.argv) > 3:
        import shutil

        for src, dst in (("lineup.jpg", "img/cast-lineup.jpg"), ("faces.jpg", "img/cast-faces.jpg"), ("cast.json", "cast.json")):
            shutil.copy(os.path.join(sys.argv[3], src), os.path.join(page, dst))
    stats = {c: glb_stats(os.path.join(ANIM, f + ".glb")) for c, f in FILES.items() if os.path.exists(os.path.join(ANIM, f + ".glb"))}
    with open(os.path.join(page, "stats.json"), "w") as f:
        json.dump(stats, f, indent=1)
    for c, s in stats.items():
        print(f"{c}: {s['triangles']} triangles, {s['vertices']} vertices, {s['bip_bones']} J_Bip bones (+{s['spring_bones']} spring), {len(s['materials'])} materials, "
              f"{s['textures']} textures ({s['texture_bytes'] // 1024} KiB), {s['morph_targets']} morph targets, {s['spring_groups']} spring groups, {s['bytes'] // 1024} KiB")


if __name__ == "__main__":
    main()
