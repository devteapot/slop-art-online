#!/usr/bin/env python3
"""Photograph five generated foundation GLBs in the game and compose a head judging sheet."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

import numpy as np
from PIL import Image, ImageDraw, ImageFont

TOOLS = Path(__file__).resolve().parents[2]
ROOT = TOOLS.parents[1]
VIEW = ROOT / "living/game/assets/view"
sys.path.insert(0, str(TOOLS))

from merge_primitives import read_glb, write_glb  # noqa: E402

MIXES = ("base", "woman", "man", "elder", "child")
EXPRESSIONS = (
    "neutral", "Fcl_EYE_Close", "Fcl_MTH_A", "Fcl_EYE_Joy",
    "Fcl_BRW_Angry", "Fcl_BRW_Surprised",
)
ANGLES = {
    "Front": "front",
    "Three-quarter": "three-quarter",
    "Left profile": "90:0",
    "Right profile": "-90:0",
}
PLAY = {"Near": "near@0", "Middle": "middle@0"}
IDLE = "idle@1/"
ORTHO_SIZE = 1440
ORTHO_METRES = 2.15
TILE = 280
LABEL = 26
GAP = 8


def sha256(path):
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def prepare(source, staging):
    inputs = {}
    for mix in MIXES:
        glb = source / f"{mix}.glb"
        if not glb.is_file() or not glb.with_suffix(".face.png").is_file():
            raise ValueError(f"expected {glb} and its .face.png sidecar")
        sidecars = sorted(p for p in source.glob(f"{mix}.*") if p != glb and p.is_file())
        inputs[mix] = {p.name: sha256(p) for p in (glb, *sidecars)}
        document, buf = read_glb(glb)
        # Keep identity weights, force one expression at a time, and render the
        # existing morph geometry through the game. Keep rigs and clip data.
        face_meshes = set()
        targets = set()
        for i, mesh in enumerate(document["meshes"]):
            names = mesh.get("extras", {}).get("targetNames", [])
            if any(name.startswith("Fcl_") for name in names):
                face_meshes.add(i)
                targets.update(names)
        missing = set(EXPRESSIONS[1:]) - targets
        if missing:
            raise ValueError(f"{glb} lacks expression targets: {', '.join(sorted(missing))}")
        if not any(anim.get("name") == "idle" for anim in document.get("animations", [])):
            raise ValueError(f"{glb} needs its embedded idle clip")

        # Mesh defaults and per-node overrides both keep their identity weights.
        face_nodes = [node for node in document["nodes"] if node.get("mesh") in face_meshes]
        for i in face_meshes:
            mesh = document["meshes"][i]
            names = mesh["extras"]["targetNames"]
            mesh.setdefault("weights", [0.0] * len(names))
        controls = [(document["meshes"][i], i) for i in sorted(face_meshes)]
        controls += [(node, node["mesh"]) for node in face_nodes if "weights" in node]
        for expression in (*EXPRESSIONS[1:], "neutral"):
            for control, i in controls:
                names = document["meshes"][i]["extras"]["targetNames"]
                for index, name in enumerate(names):
                    if name.startswith("Fcl_"):
                        control["weights"][index] = float(name == expression)
            write_variant(staging, mix, expression, document, buf, sidecars)

        # Remove the body mesh for the face-only comparison. Leave the nodes
        # and skins in place so the rig and clip retain their original indices.
        for node in document["nodes"]:
            if "mesh" in node and node["mesh"] not in face_meshes:
                node.pop("mesh")
                node.pop("skin", None)
                node.pop("weights", None)
        write_variant(staging, mix, "face-only", document, buf, sidecars)
    return inputs


def write_variant(staging, mix, name, document, buf, sidecars):
    stem = f"{mix}-{name}"
    write_glb(staging / f"{stem}.glb", document, buf)
    for path in sidecars:
        shutil.copyfile(path, staging / (stem + path.name[len(mix):]))


def render(staging, captures, stems, cameras, *, ortho=False, face_only=False):
    env = {
        key: value for key, value in os.environ.items()
        if not key.startswith(("LIVING_GAME_", "LIVING_VIEW_"))
    }
    env.update(
        CARGO_BUILD_JOBS="8",
        CARGO_TARGET_DIR=str(ROOT / ".local/head-sheet-target"),
        LIVING_GAME_SIZE=f"{ORTHO_SIZE}x{ORTHO_SIZE}" if ortho else "1600x900",
        LIVING_GAME_HOUR="11",
        LIVING_GAME_DAY_MINUTES="0",
        LIVING_GAME_VIEW_SHOTS=",".join(IDLE + camera for camera in cameras),
        LIVING_GAME_VIEW_CLIP="idle",
        LIVING_GAME_VIEW_PLATE="1" if ortho else "0",
        LIVING_GAME_VIEW_ORTHO="1" if ortho else "0",
        LIVING_GAME_VIEW_ORTHO_M=str(ORTHO_METRES),
    )
    if ortho and not face_only:
        env["LIVING_GAME_VIEW_ORTHO_Y"] = "1.02"
    lock = Path.home() / ".local/state/slop-build/gate.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    files = ",".join(str(staging / f"{stem}.glb") for stem in stems)
    subprocess.run(
        ["flock", "-s", str(lock), str(TOOLS / "view_assets.sh"), str(captures), files],
        cwd=ROOT, env=env, check=True,
    )
    for stem in stems:
        report = json.loads((captures / stem / "report.json").read_text())
        if report.get("error") or report["triangles"] == 0:
            raise ValueError(f"asset viewer did not load {stem}")


def capture_path(folder, index):
    photos = [
        p for p in folder.glob(f"{index:02d}-*.png")
        if not p.name.endswith(".plate.png")
    ]
    if len(photos) != 1:
        raise ValueError(f"expected exactly one screenshot {index:02d} in {folder}")
    return photos[0]


def portrait_crop(path, face_only):
    meta = json.loads(path.with_suffix(".ortho.json").read_text())
    px_per_m = meta["px_per_m"]
    if abs(px_per_m - ORTHO_SIZE / ORTHO_METRES) > 0.01 or meta["pitch_deg"] != 0:
        raise ValueError(f"unexpected projection for {path}")
    photo = np.asarray(Image.open(path).convert("RGB"), dtype=np.int16)
    plate = np.asarray(Image.open(path.with_suffix(".plate.png")).convert("RGB"), dtype=np.int16)
    h, w = photo.shape[:2]
    # The plate removes the checker and sky. Restrict crown detection to the
    # middle of the frame and ignore rows with only a few changed pixels.
    half = round(0.38 * px_per_m)
    changed = np.max(np.abs(photo[:, w // 2 - half:w // 2 + half] -
                            plate[:, w // 2 - half:w // 2 + half]), axis=2) > 8
    rows = np.flatnonzero(changed.sum(axis=1) >= 5)
    if not rows.size or rows[0] == 0:
        raise ValueError(f"head absent or clipped at the top of {path}")
    side = round((0.32 if face_only else 0.40) * px_per_m)
    top = int(rows[0]) - round(0.035 * px_per_m)
    if top < 0 or top + side > h:
        raise ValueError(f"head crop outside {path}")
    crown = changed[rows[0]:rows[0] + round(0.08 * px_per_m)]
    columns = np.flatnonzero(crown.any(axis=0))
    centre = w // 2 - half + round((columns[0] + columns[-1]) / 2)
    left = centre - side // 2
    return (left, top, left + side, top + side), px_per_m


def compose(captures, output, commit):
    sections = (
        ("Neutral faces · shared scale", ("Face-only front",)),
        ("Neutral · level views", tuple(ANGLES)),
        ("Expressions · front", EXPRESSIONS),
        ("Play camera · native pixels", tuple(PLAY)),
    )
    pitch = TILE + GAP
    row_height = TILE + LABEL + GAP
    height = GAP + sum(32 + len(rows) * row_height for _, rows in sections)
    sheet = Image.new("RGB", (GAP + len(MIXES) * pitch, height), "#212931")
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 13)
        header = ImageFont.truetype("DejaVuSans.ttf", 18)
    except OSError:
        font = header = ImageFont.load_default()

    shot_list = []
    front_crops = {}
    y = GAP
    for section, rows in sections:
        draw.text((GAP, y + 4), section, font=header, fill="white")
        y += 32
        for index, view in enumerate(rows):
            for column, mix in enumerate(MIXES):
                expression = "neutral"
                if view == "Face-only front":
                    camera = "front"
                    path = capture_path(captures / "face-only" / f"{mix}-face-only", 0)
                    crop, scale = portrait_crop(path, face_only=True)
                elif view in ANGLES:
                    camera = ANGLES[view]
                    path = capture_path(captures / "neutral" / f"{mix}-neutral", index)
                    crop, scale = portrait_crop(path, face_only=False)
                    if view == "Front":
                        front_crops[mix] = (path, crop, scale)
                elif view in EXPRESSIONS:
                    camera = "front"
                    expression = view
                    front, crop, scale = front_crops[mix]
                    path = front if expression == "neutral" else capture_path(
                        captures / mix / f"{mix}-{expression}", 0
                    )
                else:
                    camera = PLAY[view]
                    path = capture_path(captures / "play" / f"{mix}-neutral", index)
                    with Image.open(path) as photo:
                        x0, y0 = (photo.width - TILE) // 2, (photo.height - TILE) // 2
                    crop, scale = (x0, y0, x0 + TILE, y0 + TILE), None

                with Image.open(path) as photo:
                    tile = photo.convert("RGB").crop(crop)
                if scale is not None:
                    tile = tile.resize((TILE, TILE), Image.Resampling.LANCZOS)
                x = GAP + column * pitch
                draw.text((x + 3, y + 4), f"{mix} · {view} · {commit[:9]}", font=font, fill="white")
                sheet.paste(tile, (x, y + LABEL))
                shot_list.append({
                    "mix": mix, "view": view, "expression": expression,
                    "shot": IDLE + camera, "projection": "orthographic" if scale else "perspective",
                    "capture_px_per_m": scale, "crop_px": list(crop),
                    "sheet_xy_px": [x, y + LABEL],
                })
            y += row_height
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output)
    return shot_list


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, help="assets/view subdirectory with MIX.glb and sidecars")
    parser.add_argument("output", type=Path, help="PNG path; its JSON manifest is written beside it")
    parser.add_argument("--commit", help="generator commit to label (defaults to HEAD)")
    parser.add_argument("--checkpoint-hashes", type=Path, help="compare with Stage 2 hand-checks.json")
    args = parser.parse_args()
    source = args.directory.resolve()
    if not source.is_relative_to(VIEW.resolve()) or source == VIEW.resolve():
        parser.error("input directory must be below living/game/assets/view")
    if not source.is_dir():
        parser.error(f"input directory does not exist: {source}")
    if args.output.suffix.lower() != ".png":
        parser.error("output must be a .png")
    commit = subprocess.check_output(
        ["git", "rev-parse", "--verify", f"{args.commit or 'HEAD'}^{{commit}}"],
        cwd=ROOT, text=True,
    ).strip()
    (ROOT / ".local").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="head-sheet-", dir=VIEW) as assets, \
         tempfile.TemporaryDirectory(prefix="head-sheet-", dir=ROOT / ".local") as shots:
        staging, captures = Path(assets), Path(shots)
        inputs = prepare(source, staging)
        manifest = {"commit": commit, "inputs_sha256": inputs, "light_hour": 11}
        if args.checkpoint_hashes:
            expected = json.loads(args.checkpoint_hashes.read_text())
            comparison = {
                mix: {"expected": expected[f"{mix}-l2"]["glb_sha256"],
                      "match": files[f"{mix}.glb"] == expected[f"{mix}-l2"]["glb_sha256"]}
                for mix, files in inputs.items()
            }
            manifest["checkpoint_hashes"] = comparison
            if not all(entry["match"] for entry in comparison.values()):
                raise ValueError(f"checkpoint hash mismatch: {comparison}")
        neutral = [f"{mix}-neutral" for mix in MIXES]
        render(staging, captures / "neutral", neutral, ANGLES.values(), ortho=True)
        for mix in MIXES:
            render(staging, captures / mix, [f"{mix}-{e}" for e in EXPRESSIONS[1:]], ["front"], ortho=True)
        render(staging, captures / "face-only", [f"{mix}-face-only" for mix in MIXES],
               ["front"], ortho=True, face_only=True)
        render(staging, captures / "play", neutral, PLAY.values())
        manifest["shots"] = compose(captures, args.output, commit)
        args.output.with_suffix(".json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Wrote {args.output} and {args.output.with_suffix('.json')}")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        sys.exit(f"head_sheet: {error}")
