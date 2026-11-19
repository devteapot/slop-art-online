#!/usr/bin/env python3
"""The calibration frame for hand-made characters (docs/HANDMADE_HAIR.md, "The calibration frame").

    python3 living/tools/characters/calibrate.py view/own-cora-live.glb [--targets T.json] [--out DIR]
                                                 [--binary PATH] [--no-run] [--also SHOT ...]

`just living-game-calibrate view/<file>.glb` builds the client and runs this.

1. **Audit:** checks the file against the contract: the scene's `slop` (contract, character,
   forward, and the face's own direction), every material's slot, the hair profile (four sRGB
   swatches, t2 above t1), the highlight mask (`_HIGHLIGHT`'s accessor and coverage, or the mask
   texture), the face's TEXCOORD_1 and shadow map, the tint's alpha mode. Errors make the run fail.
2. **Frame:** the asset view, headless, 1600x900, the default grade, the sun fixed at 11:00, the
   idle clip at 0 s (the first clip if there is no idle), three shots: `portrait` (yaw 0, pitch
   8, aim 0.88), `near` (the game camera's Near stop) and `portrait45` (yaw 45). `--also` adds
   view shots (`middle@0`, the Middle stop).
3. **Measure:** the targets file (default `<stem>.calibration.json` beside the GLB) names
   patches. Each patch's **target** is the colour the calibrated frame must show: `"target":
   [r, g, b]` (display sRGB), or `"drawing": [x, y]`, the 9x9 median of the drawing (`"drawing":
   "path.png"` at the top) there. Each shot key (`portrait`, `near`, `portrait45`) gives the
   pixel to measure in that shot (9x9 median). A patch passes when every channel is within its
   tolerance: `"tolerance"` on the patch, else the file's `"tolerance": {"hair": 8, "other":
   10}` by whether the name starts with "hair", else 8 and 10. A patch may name the palette
   swatch it tunes (`"swatch": "mid"`); the report then suggests that swatch's next value
   (each linear channel scaled by target / measured, averaged over the shots).

Writes OUT (default `.local/living/calibrate/<stem>/<time>/`): `stills/<stem>/NN-<shot>.png`,
`client.log`, `colours.csv`, `report.json`. Plain Python, no dependencies.
"""

import argparse
import csv
import json
import os
import struct
import subprocess
import sys
import time
import zlib
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
ASSETS = REPO / "living" / "game" / "assets"
SLOTS = {"hair", "skin", "face", "eyes", "tint", "cloth"}
SWATCHES = ("shade", "mid", "light", "highlight")
HAIR_KEYS = set(SWATCHES) | {"t1", "t2", "edge", "highlight_feather", "highlight_map"}
SHOTS = ("portrait", "near", "portrait45")
FLOAT, SCALAR = 5126, "SCALAR"


# ---- glTF ------------------------------------------------------------------------------------

def read_glb(path):
    b = Path(path).read_bytes()
    if b[:4] != b"glTF":
        raise SystemExit(f"calibrate: {path} is not a GLB")
    n = struct.unpack("<I", b[12:16])[0]
    j = json.loads(b[20 : 20 + n])
    off = 20 + n
    binary = b""
    if off + 8 <= len(b):
        bl = struct.unpack("<I", b[off : off + 4])[0]
        binary = b[off + 8 : off + 8 + bl]
    return j, binary


def accessor(j, binary, i):
    a = j["accessors"][i]
    comp = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}[a["type"]]
    if a.get("componentType") != FLOAT or "bufferView" not in a:
        return None, a
    bv = j["bufferViews"][a["bufferView"]]
    start = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
    stride = bv.get("byteStride", 4 * comp)
    vals = []
    for k in range(a["count"]):
        o = start + k * stride
        vals.append(struct.unpack_from(f"<{comp}f", binary, o))
    return vals, a


# ---- PNG -------------------------------------------------------------------------------------

def read_png(path):
    """An 8-bit RGB or RGBA PNG as (width, height, channels, rows of bytes)."""
    b = Path(path).read_bytes()
    pos, idat, w = 8, [], None
    while pos < len(b):
        n = struct.unpack(">I", b[pos : pos + 4])[0]
        tag = b[pos + 4 : pos + 8]
        data = b[pos + 8 : pos + 8 + n]
        if tag == b"IHDR":
            w, h, depth, ctype, _, _, interlace = struct.unpack(">IIBBBBB", data)
            if depth != 8 or ctype not in (0, 2, 6) or interlace:
                raise ValueError(f"{path}: only 8-bit, non-interlaced grey/RGB/RGBA PNGs are read")
        elif tag == b"IDAT":
            idat.append(data)
        elif tag == b"IEND":
            break
        pos += 12 + n
    ch = {0: 1, 2: 3, 6: 4}[ctype]
    raw = zlib.decompress(b"".join(idat))
    stride = w * ch
    rows, prev = [], bytearray(stride)
    for y in range(h):
        f = raw[y * (stride + 1)]
        line = bytearray(raw[y * (stride + 1) + 1 : (y + 1) * (stride + 1)])
        if f == 1:
            for i in range(ch, stride):
                line[i] = (line[i] + line[i - ch]) & 255
        elif f == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 255
        elif f == 3:
            for i in range(stride):
                left = line[i - ch] if i >= ch else 0
                line[i] = (line[i] + ((left + prev[i]) >> 1)) & 255
        elif f == 4:
            for i in range(stride):
                a = line[i - ch] if i >= ch else 0
                c = prev[i - ch] if i >= ch else 0
                bb = prev[i]
                p = a + bb - c
                pa, pb, pc = abs(p - a), abs(p - bb), abs(p - c)
                pr = a if pa <= pb and pa <= pc else (bb if pb <= pc else c)
                line[i] = (line[i] + pr) & 255
        rows.append(line)
        prev = line
    return w, h, ch, rows


def patch_median(img, x, y, r=4):
    w, h, ch, rows = img
    out = []
    for c in range(3):
        vals = sorted(rows[yy][xx * ch + min(c, ch - 1)] for yy in range(max(y - r, 0), min(y + r + 1, h)) for xx in range(max(x - r, 0), min(x + r + 1, w)))
        out.append(vals[len(vals) // 2])
    return out


# ---- colour ----------------------------------------------------------------------------------

def to_linear(c):
    c = c / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def to_srgb(l):
    l = max(0.0, min(1.0, l))
    v = l * 12.92 if l <= 0.0031308 else 1.055 * l ** (1 / 2.4) - 0.055
    return round(v * 255)


def luminance(rgb):
    r, g, b = (to_linear(v) for v in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def saturation(rgb):
    hi, lo = max(rgb), min(rgb)
    return 0.0 if hi == 0 else (hi - lo) / hi


# ---- the audit -------------------------------------------------------------------------------

def audit(glb):
    """(errors, warnings, notes, facts) of a file against the contract."""
    errors, warns, notes, facts = [], [], [], {}
    j, binary = read_glb(ASSETS / glb if not os.path.isabs(glb) else glb)
    stem = str(glb)[: -len(".glb")] if str(glb).endswith(".glb") else str(glb)
    scene = j.get("scenes", [{}])[j.get("scene", 0)]
    slop = scene.get("extras", {}).get("slop")
    if slop is None:
        notes.append("no slop extras on the scene: the client draws this file as before (not a hand-made character)")
        return errors, warns, notes, facts
    if slop.get("contract") != 1:
        errors.append(f"scene: slop.contract is {slop.get('contract')!r}, not 1")
    if slop.get("character") != "handmade":
        errors.append(f"scene: slop.character is {slop.get('character')!r}, not \"handmade\"")
    fwd = slop.get("forward")
    if fwd not in ("+Z", "-Z"):
        errors.append(f"scene: slop.forward is {fwd!r}, not \"+Z\" or \"-Z\"")
    facts["forward"] = fwd
    mats = j.get("materials", [])
    slots = {}
    for i, m in enumerate(mats):
        name = m.get("name", f"material {i}")
        ms = m.get("extras", {}).get("slop")
        if ms is None or "slot" not in ms:
            warns.append(f"material {name!r}: no slop.slot; the client classes it by its name")
            continue
        s = ms["slot"]
        if s not in SLOTS:
            errors.append(f"material {name!r}: slot {s!r} is not one of {sorted(SLOTS)} (drawn as cloth)")
            continue
        slots[i] = s
        if "hair" in ms and s != "hair":
            errors.append(f"material {name!r}: a hair profile on a {s!r} slot (ignored)")
        if s == "hair" and "hair" in ms:
            h = ms["hair"]
            for k in SWATCHES:
                v = h.get(k)
                if not (isinstance(v, list) and len(v) == 3 and all(isinstance(x, int) and 0 <= x <= 255 for x in v)):
                    errors.append(f"material {name!r}: hair.{k} is {v!r}, not three integers 0-255 (the profile is ignored)")
            for k in ("t1", "t2", "edge", "highlight_feather"):
                if k in h and not isinstance(h[k], (int, float)):
                    errors.append(f"material {name!r}: hair.{k} is not a number")
            t1, t2 = h.get("t1", -0.2), h.get("t2", 0.4)
            if isinstance(t1, (int, float)) and isinstance(t2, (int, float)) and t2 <= t1:
                errors.append(f"material {name!r}: hair.t2 {t2} is not above t1 {t1} (the profile is ignored)")
            for k in sorted(set(h) - HAIR_KEYS):
                warns.append(f"material {name!r}: hair.{k} is not a contract key (ignored)")
            facts.setdefault("profiles", {})[name] = h
            facts.setdefault("hair_materials", []).append(i)
        if s == "tint" and m.get("alphaMode", "OPAQUE") == "OPAQUE":
            warns.append(f"material {name!r}: an opaque tint multiplies its whole surface; give it BLEND and alpha")
    facts["slots"] = {mats[i].get("name", str(i)): s for i, s in slots.items()}
    # Primitives by slot.
    face_dir, face_prims, hair_prims = [0.0, 0.0, 0.0], [], []
    for mesh in j.get("meshes", []):
        for p in mesh.get("primitives", []):
            s = slots.get(p.get("material"))
            if s == "face":
                face_prims.append(p)
            if s == "hair" and p.get("material") in facts.get("hair_materials", []):
                hair_prims.append(p)
            if s in ("face", "eyes") and "NORMAL" in p["attributes"]:
                nor, _ = accessor(j, binary, p["attributes"]["NORMAL"])
                for n in nor or []:
                    for k in range(3):
                        face_dir[k] += n[k]
    if fwd in ("+Z", "-Z") and abs(face_dir[2]) > 1e-6:
        seen = "+Z" if face_dir[2] > 0 else "-Z"
        facts["face_normals_point"] = seen
        if seen != fwd:
            errors.append(f"scene: forward is {fwd} but the face's and eyes' normals point {seen} on average")
    # The highlight mask.
    tex = None
    for name, h in facts.get("profiles", {}).items():
        for cand in ([h["highlight_map"]] if h.get("highlight_map") else []) + [stem + ".hair.png"]:
            for f in (cand[:-4] + ".ktx2", cand):
                if (ASSETS / f).exists():
                    tex = tex or f
    if tex:
        facts["mask"] = f"texture {tex}"
        if not tex.endswith(".ktx2"):
            try:
                w, hh, ch, _ = read_png(ASSETS / tex)
                facts["mask_texture"] = f"{w}x{hh}, {ch} channel(s)"
            except ValueError as e:
                errors.append(f"mask texture: {e}")
    if hair_prims:
        total, high, has = 0, 0, False
        for p in hair_prims:
            if "TEXCOORD_1" in p["attributes"]:
                warns.append("a profile hair primitive carries TEXCOORD_1; the client replaces it")
            a = p["attributes"].get("_HIGHLIGHT")
            if a is None:
                continue
            has = True
            vals, acc = accessor(j, binary, a)
            if vals is None or acc["type"] != SCALAR or acc.get("normalized"):
                errors.append("_HIGHLIGHT is not a SCALAR FLOAT accessor (not normalized)")
                continue
            if any(v[0] < 0 or v[0] > 1 for v in vals):
                warns.append("_HIGHLIGHT has values outside 0-1 (clamped)")
            total += len(vals)
            high += sum(1 for v in vals if v[0] > 0.5)
        if has and total:
            facts["highlight_vertices"] = f"{high} of {total} hair vertices above 0.5 ({100 * high / total:.1f}%)"
            if tex:
                warns.append("both _HIGHLIGHT and a mask texture: the texture wins, _HIGHLIGHT is ignored")
            else:
                facts["mask"] = "per vertex (_HIGHLIGHT)"
            if high == 0:
                warns.append("_HIGHLIGHT is never above 0.5: no highlight is drawn")
        elif not tex:
            warns.append("a hair profile without _HIGHLIGHT or a mask texture: three bands, no highlight")
    # The face.
    if face_prims:
        for p in face_prims:
            a = p["attributes"]
            if "JOINTS_0" not in a:
                errors.append("the face is not skinned: its forward (TEXCOORD_1) is not turned with the head")
            if "TEXCOORD_1" not in a:
                errors.append("the face has no TEXCOORD_1 (its forward): it shades as skin")
                continue
            vals, acc = accessor(j, binary, a["TEXCOORD_1"])
            if vals is None or acc["type"] != "VEC2":
                errors.append("the face's TEXCOORD_1 is not a VEC2 FLOAT")
                continue
            first = vals[0]
            if any(abs(v[0] - first[0]) > 1e-4 or abs(v[1] - first[1]) > 1e-4 for v in vals):
                errors.append("the face's TEXCOORD_1 is not the same on every vertex")
            want = {"+Z": (0.0, 1.0), "-Z": (0.0, -1.0)}.get(fwd)
            facts["face_forward_uv1"] = [round(first[0], 4), round(first[1], 4)]
            if want and (abs(first[0] - want[0]) > 0.02 or abs(first[1] - want[1]) > 0.02):
                errors.append(f"the face's TEXCOORD_1 is {facts['face_forward_uv1']}, not {list(want)} for forward {fwd} (in Blender the V is flipped: store 1 - v)")
        maps = [stem + ".face.ktx2", stem + ".face.png"]
        for m in mats:
            if m.get("extras", {}).get("face_map"):
                maps.append(m["extras"]["face_map"])
        found = next((f for f in maps if (ASSETS / f).exists()), None)
        if found is None:
            errors.append(f"no face shadow map ({stem}.face.png or a face_map extra): the face shades as skin")
        else:
            facts["face_map"] = found
            if found.endswith(".png"):
                try:
                    w, hh, ch, _ = read_png(ASSETS / found)
                    if w != hh or ch < 3:
                        warns.append(f"face map {found} is {w}x{hh} with {ch} channel(s); the contract asks a square RGB map")
                except ValueError as e:
                    errors.append(f"face map: {e}")
    elif slop:
        notes.append("no face slot: no face shadow (the face shades as its slot or name says)")
    anim = Path(glb).parent / "anim" / Path(glb).name
    if (ASSETS / anim).exists():
        aj, _ = read_glb(ASSETS / anim)
        if aj.get("scenes", [{}])[aj.get("scene", 0)].get("extras", {}).get("slop") != slop:
            errors.append(f"{anim} is what the client loads, and its scene slop differs from this file's")
    return errors, warns, notes, facts


# ---- the frame -------------------------------------------------------------------------------

def clips_of(glb):
    j, _ = read_glb(ASSETS / glb)
    return [a.get("name", f"clip{i}") for i, a in enumerate(j.get("animations", []))]


def run_frame(glb, binary, out, also):
    clips = clips_of(glb)
    clip = "idle" if "idle" in clips else (clips[0] if clips else None)
    views = ["0:8:0.36:0.88", "near@0", "45:8:0.36:0.88"] + list(also)
    shots = ",".join(f"{clip}@0/{v}" if clip else v for v in views)
    env = {k: v for k, v in os.environ.items() if not k.startswith("LIVING_GAME_")}
    env.update(
        LIVING_GAME_VIEW=str(glb),
        LIVING_GAME_VIEW_SHOTS=shots,
        LIVING_GAME_VIEW_OUT=str(out / "stills"),
        LIVING_GAME_HOUR="11",
        LIVING_GAME_DAY_MINUTES="0",
        LIVING_GAME_FILM="soft",
        LIVING_GAME_HAIR_SHINE="crown",
        LIVING_GAME_SETTINGS=str(out / "settings.json"),
        LIVING_GAME_SIZE="1600x900",
        RUST_LOG=os.environ.get("RUST_LOG", "warn,living_game=info"),
    )
    if clip:
        env["LIVING_GAME_VIEW_CLIP"] = clip
    with (out / "client.log").open("w") as log:
        subprocess.run([str(binary)], env=env, stdout=log, stderr=subprocess.STDOUT, timeout=240, check=True)
    stem = Path(glb).stem
    stills = sorted((out / "stills" / stem).glob("[0-9][0-9]-*.png"))
    names = list(SHOTS) + [a.replace("@", "_") for a in also]
    return {names[i]: p for i, p in enumerate(stills) if i < len(names)}


def measure(targets_path, shots, profiles):
    t = json.loads(Path(targets_path).read_text())
    drawing = None
    if t.get("drawing"):
        dp = Path(t["drawing"])
        dp = dp if dp.is_absolute() else Path(targets_path).parent / dp
        if dp.exists():
            drawing = read_png(dp)
        elif any(not p.get("target") for p in t.get("patches", {}).values()):
            print(f"  WARN: no drawing {dp}: patches without a \"target\" are skipped")
    tol = {"hair": 8, "other": 10, **t.get("tolerance", {})}
    imgs = {k: read_png(p) for k, p in shots.items()}
    rows, suggest = [], {}
    for name, p in t.get("patches", {}).items():
        if p.get("target"):
            target = list(p["target"])
        elif p.get("drawing") and drawing and any(p["drawing"]):
            target = patch_median(drawing, *p["drawing"])
        else:
            continue
        limit = p.get("tolerance", tol["hair"] if name.lower().startswith("hair") else tol["other"])
        for shot in SHOTS:
            at = p.get(shot)
            if not at or not any(at) or shot not in imgs:
                continue
            got = patch_median(imgs[shot], *at)
            d = [g - tg for g, tg in zip(got, target)]
            ok = all(abs(x) <= limit for x in d)
            rows.append(dict(patch=name, shot=shot, x=at[0], y=at[1], target=target, measured=got, delta=d, tolerance=limit, passed=ok,
                             luminance=round(luminance(got), 4), target_luminance=round(luminance(target), 4),
                             saturation=round(saturation(got), 4), target_saturation=round(saturation(target), 4)))
            sw = p.get("swatch")
            if sw in SWATCHES and profiles:
                cur = next(iter(profiles.values())).get(sw)
                if cur:
                    ratio = [to_linear(tg) / max(to_linear(g), 1e-4) for tg, g in zip(target, got)]
                    suggest.setdefault(sw, []).append([to_linear(c) * r for c, r in zip(cur, ratio)])
    suggested = {k: [to_srgb(sum(v[i] for v in vs) / len(vs)) for i in range(3)] for k, vs in suggest.items()}
    return rows, suggested


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("glb", help="the file, as a path under living/game/assets (view/<file>.glb)")
    ap.add_argument("--targets", help="patch targets (default <stem>.calibration.json beside the file)")
    ap.add_argument("--out")
    ap.add_argument("--binary", help="the game client (default $CARGO_TARGET_DIR or living/target, release)")
    ap.add_argument("--no-run", action="store_true", help="audit only")
    ap.add_argument("--also", action="append", default=[], help="another view shot, e.g. middle@0")
    a = ap.parse_args()
    glb = a.glb
    if os.path.isabs(glb):
        glb = os.path.relpath(glb, ASSETS)
    stem = Path(glb).stem
    errors, warns, notes, facts = audit(glb)
    print(f"calibrate: {glb}")
    for k, v in facts.items():
        print(f"  {k}: {v}")
    for n in notes:
        print(f"  note: {n}")
    for w in warns:
        print(f"  WARN: {w}")
    for e in errors:
        print(f"  ERROR: {e}")
    print(f"  audit: {len(errors)} error(s), {len(warns)} warning(s)")
    if a.no_run:
        sys.exit(1 if errors else 0)
    out = Path(a.out) if a.out else REPO / ".local" / "living" / "calibrate" / stem / time.strftime("%Y%m%d-%H%M%S")
    out.mkdir(parents=True, exist_ok=True)
    target_dir = Path(os.environ.get("CARGO_TARGET_DIR", REPO / "living" / "target"))
    binary = Path(a.binary) if a.binary else target_dir / "release" / "living-game"
    shots = run_frame(glb, binary, out, a.also)
    print(f"  stills: {out / 'stills' / stem}")
    for k, p in shots.items():
        print(f"    {k}: {p.name}")
    targets = Path(a.targets) if a.targets else ASSETS / (str(glb)[:-4] + ".calibration.json")
    rows, suggested = ([], {})
    if targets.exists():
        rows, suggested = measure(targets, shots, facts.get("profiles", {}))
    else:
        print(f"  no targets file {targets}: stills only")
    with (out / "colours.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["patch", "shot", "x", "y", "target_R", "target_G", "target_B", "R", "G", "B", "dR", "dG", "dB", "tolerance", "passed", "luminance", "target_luminance", "saturation", "target_saturation"])
        for r in rows:
            w.writerow([r["patch"], r["shot"], r["x"], r["y"], *r["target"], *r["measured"], *r["delta"], r["tolerance"], r["passed"], r["luminance"], r["target_luminance"], r["saturation"], r["target_saturation"]])
    if rows:
        print(f"  {'patch':<16} {'shot':<11} {'target':<15} {'measured':<15} {'delta':<16} result")
        for r in rows:
            print(f"  {r['patch']:<16} {r['shot']:<11} {str(tuple(r['target'])):<15} {str(tuple(r['measured'])):<15} {str(tuple(r['delta'])):<16} {'pass' if r['passed'] else 'FAIL'} (±{r['tolerance']})")
    for k, v in suggested.items():
        print(f"  suggest hair.{k}: {v}")
    passed = not errors and all(r["passed"] for r in rows)
    report = dict(file=glb, out=str(out), audit=dict(errors=errors, warnings=warns, notes=notes, facts=facts), shots={k: str(p) for k, p in shots.items()}, patches=rows, suggested=suggested, passed=passed)
    (out / "report.json").write_text(json.dumps(report, indent=2, default=str))
    print(f"  calibration: {'PASS' if passed else 'FAIL'} ({sum(r['passed'] for r in rows)} of {len(rows)} patches within tolerance; report {out / 'report.json'})")
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
