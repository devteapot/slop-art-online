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
   pixel to measure in that shot (9x9 median; `"sample": "min5"`, for ink lines, the darkest
   pixel of a 5x5 window instead). A patch passes when every channel is within its
   tolerance: `"tolerance"` on the patch, else the file's `"tolerance": {"hair": 8, "other":
   10}` by whether the name starts with "hair", else 8 and 10. A patch may name the palette
   swatch it tunes (`"swatch": "mid"`); the report then suggests that swatch's next value
   (each linear channel scaled by target / measured, averaged over the shots).

**Ink (contract v1.2, docs/HANDMADE_INK.md):** the audit checks every material's `slop.ink` (its
fields, its map, its primitives' UV0, the range against the width, a carrier's alpha mode and
morph targets). An ink patch may say which ink it tunes (`"slot"`, and `"material"` when a slot
has several inked materials; `"swatch": "ink"` then suggests that material's `ink.color`, and
without `"slot"` the hair profile's v1.1 `ink`) and take a floor-relative target: `"relative":
"<reference patch>"` gives, per shot and per linear channel, floor + (drawing ink / drawing
reference) x (measured reference - floor), encoded and rounded once. The floor is `"floor": [r,
g, b]`, or (`"control"`, the default) the patch's min5 in a control render of a temporary copy
whose slot is black (base colours, a hair profile's swatches and every ink).

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
INK_KEYS = ("ink", "ink_px", "ink_range", "ink_fade_px")
HAIR_KEYS = set(SWATCHES) | {"t1", "t2", "edge", "highlight_feather", "highlight_map"} | set(INK_KEYS)
SHOTS = ("portrait", "near", "portrait45")
FLOAT, SCALAR = 5126, "SCALAR"
INK_FIELDS = {"color", "width", "px", "min_px", "range", "fade_px", "map", "taper"}
NEAR_M_PX = 0.00805  # a pixel's metres at the Near stop (toon.wesl INK_NEAR_M_PX)


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
            if depth != 8 or ctype not in (0, 2, 4, 6) or interlace:
                raise ValueError(f"{path}: only 8-bit, non-interlaced grey, grey-alpha, RGB or RGBA PNGs are read")
        elif tag == b"IDAT":
            idat.append(data)
        elif tag == b"IEND":
            break
        pos += 12 + n
    ch = {0: 1, 2: 3, 4: 2, 6: 4}[ctype]
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


def patch_min(img, x, y, r=2):
    """The darkest pixel (by luminance) of a (2r+1)² window: for thin ink lines."""
    w, h, ch, rows = img
    best = None
    for yy in range(max(y - r, 0), min(y + r + 1, h)):
        for xx in range(max(x - r, 0), min(x + r + 1, w)):
            px = rows[yy][xx * ch : xx * ch + 3] if ch >= 3 else [rows[yy][xx * ch]] * 3
            lum = 0.2126 * px[0] + 0.7152 * px[1] + 0.0722 * px[2]
            if best is None or lum < best[0]:
                best = (lum, list(px))
    return best[1]


def patch_median(img, x, y, r=4):
    w, h, ch, rows = img
    out = []
    for c in range(3):
        vals = sorted(rows[yy][xx * ch + (c if ch >= 3 else 0)] for yy in range(max(y - r, 0), min(y + r + 1, h)) for xx in range(max(x - r, 0), min(x + r + 1, w)))
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
                facts["mask"] = f"per vertex (_HIGHLIGHT) and texture {tex}: the larger of the two (v1.1)"
            else:
                facts["mask"] = "per vertex (_HIGHLIGHT)"
            if high == 0:
                warns.append("_HIGHLIGHT is never above 0.5: no highlight is drawn")
        elif not tex:
            warns.append("a hair profile without _HIGHLIGHT or a mask texture: three bands, no highlight")
    # Lock ink (v1.1): warnings only.
    profiles = facts.get("profiles", {})
    inked = {n: h for n, h in profiles.items() if any(k in h for k in INK_KEYS)}
    g_lines = None
    if tex:
        png = tex[:-5] + ".png" if tex.endswith(".ktx2") else tex
        if (ASSETS / png).exists():
            try:
                w, hh, ch, rows = read_png(ASSETS / png)
                if ch >= 3:
                    on = sum(1 for r in rows for x in range(w) if r[x * ch + 1] == 0)
                    near = sum(1 for r in rows for x in range(w) if r[x * ch + 1] < 255)
                    g_lines = near > 0
                    facts["ink_field"] = f"G: {on} texels on a line, {100 * near / (w * hh):.1f}% within range"
                else:
                    facts["ink_field"] = "no G (a greyscale texture): no ink"
            except ValueError:
                pass
    for name, h in inked.items():
        r = h.get("ink_range", 0.004)
        if not isinstance(r, (int, float)) or r <= 0:
            warns.append(f"material {name!r}: hair.ink_range is {r!r}; it must be a number above 0 (no ink is drawn)")
        for k in ("ink_px", "ink_fade_px"):
            if k in h and (not isinstance(h[k], (int, float)) or h[k] <= 0):
                warns.append(f"material {name!r}: hair.{k} is {h[k]!r}, not a number above 0")
        if "ink" in h and not (isinstance(h["ink"], list) and len(h["ink"]) == 3 and all(isinstance(x, int) and 0 <= x <= 255 for x in h["ink"])):
            warns.append(f"material {name!r}: hair.ink is {h['ink']!r}, not three integers 0-255 (the default, shade x 0.6, is used)")
        if not tex:
            warns.append(f"material {name!r}: ink fields but no mask texture ({stem}.hair.png): no ink is drawn")
        elif g_lines is None:
            warns.append(f"material {name!r}: ink fields but the texture has no G channel: no ink is drawn")
        elif not g_lines:
            warns.append(f"material {name!r}: ink fields but the texture's G is 255 everywhere: no line")
    if not inked and g_lines:
        warns.append("the mask texture's G holds lines but no hair profile sets an ink field: no ink is drawn (set ink_range)")
    if hair_prims and (tex or inked):
        us, vs = [], []
        for p in hair_prims:
            uv, _ = accessor(j, binary, p["attributes"]["TEXCOORD_0"]) if "TEXCOORD_0" in p["attributes"] else (None, None)
            for u in uv or []:
                us.append(u[0])
                vs.append(u[1])
        if not us or (max(us) - min(us)) * (max(vs) - min(vs)) < 1e-6:
            warns.append("the hair's TEXCOORD_0 spans no area (no UV unwrap): its mask texture and ink read one texel everywhere")
    ink_audit(j, binary, stem, mats, slots, profiles, errors, warns, facts)
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


def read_indices(j, binary, i):
    a = j["accessors"][i]
    bv = j["bufferViews"][a["bufferView"]]
    fmt = {5121: "B", 5123: "H", 5125: "I"}[a["componentType"]]
    return list(struct.unpack_from(f"<{a['count']}{fmt}", binary, bv.get("byteOffset", 0) + a.get("byteOffset", 0)))


def ink_maps(stem, slot, ink):
    """The ink map's candidates in the client's order (docs/HANDMADE_INK.md, "The map")."""
    cands = ([ink["map"]] if isinstance(ink.get("map"), str) else []) + ([f"{stem}.{slot}.ink.png"] if slot else [])
    return [f for c in cands for f in (c[: -len(".png")] + ".ktx2" if c.endswith(".png") else c, c)]


def uv_facts(j, binary, prims):
    """(per primitive: zero-area share, total UV area), and the triangles' metres per UV unit."""
    out, dens = [], []
    for p in prims:
        a = p["attributes"]
        if "TEXCOORD_0" not in a:
            out.append(None)
            continue
        pos, _ = accessor(j, binary, a["POSITION"])
        uv, _ = accessor(j, binary, a["TEXCOORD_0"])
        idx = read_indices(j, binary, p["indices"]) if "indices" in p else list(range(len(pos)))
        zero, total, n = 0, 0.0, 0
        for k in range(0, len(idx) - 2, 3):
            ia, ib, ic = idx[k : k + 3]
            ua = abs((uv[ib][0] - uv[ia][0]) * (uv[ic][1] - uv[ia][1]) - (uv[ic][0] - uv[ia][0]) * (uv[ib][1] - uv[ia][1]))
            e1 = [pos[ib][c] - pos[ia][c] for c in range(3)]
            e2 = [pos[ic][c] - pos[ia][c] for c in range(3)]
            cr = [e1[1] * e2[2] - e1[2] * e2[1], e1[2] * e2[0] - e1[0] * e2[2], e1[0] * e2[1] - e1[1] * e2[0]]
            area = sum(c * c for c in cr) ** 0.5
            n += 1
            total += ua
            if ua <= 1e-12:
                zero += 1
            elif area > 0:
                dens.append((area / ua) ** 0.5)
        out.append((zero / max(n, 1), total))
    dens.sort()
    return out, dens


def ink_audit(j, binary, stem, mats, slots, profiles, errors, warns, facts):
    """The v1.2 ink checks (docs/HANDMADE_INK.md, "The audit"): errors and warnings appended."""
    by_mat = {}
    for mi, mesh in enumerate(j.get("meshes", [])):
        for p in mesh.get("primitives", []):
            by_mat.setdefault(p.get("material"), []).append((mi, p))
    face_names = None
    for mi, mesh in enumerate(j.get("meshes", [])):
        if any(slots.get(p.get("material")) == "face" for p in mesh.get("primitives", [])):
            face_names = (mesh.get("extras") or {}).get("targetNames") or face_names
    for i, m in enumerate(mats):
        ms = m.get("extras", {}).get("slop") or {}
        if "ink" not in ms:
            continue
        name, ink, slot = m.get("name", f"material {i}"), ms["ink"], ms.get("slot")
        pre = f"material {name!r}: ink"
        if not isinstance(ink, dict):
            errors.append(f"{pre} is not an object (ignored)")
            continue
        c = ink.get("color")
        if not (isinstance(c, list) and len(c) == 3 and all(isinstance(x, int) and 0 <= x <= 255 for x in c)):
            errors.append(f"{pre}.color is {c!r}, not three integers 0-255 (the ink is ignored)")
        r = ink.get("range", 0.004)
        if not isinstance(r, (int, float)) or isinstance(r, bool) or r <= 0:
            errors.append(f"{pre}.range is {r!r}, not a number above 0 (the ink is ignored)")
            r = None
        for k in ("px", "min_px", "fade_px"):
            if k in ink and (not isinstance(ink[k], (int, float)) or isinstance(ink[k], bool) or ink[k] < 0):
                errors.append(f"{pre}.{k} is {ink[k]!r}, not a number 0 or above (the ink is ignored)")
        if "taper" in ink and not isinstance(ink["taper"], bool):
            errors.append(f"{pre}.taper is {ink['taper']!r}, not true or false (the ink is ignored)")
        mode = ink.get("width", "px")
        if mode not in ("px", "uv"):
            errors.append(f"{pre}.width is {mode!r}, not \"px\" or \"uv\" (the ink is ignored)")
        for k in sorted(set(ink) - INK_FIELDS):
            warns.append(f"{pre}.{k} is not a contract key (ignored)")
        if slot == "tint":
            errors.append(f"{pre} on a tint, which is multiplied over the skin (ignored): put the line on a carrier or the skin")
            continue
        if slot is None and not isinstance(ink.get("map"), str):
            errors.append(f"{pre} on a material without a slot needs a map (ignored)")
            continue
        if slot == "hair" and name in profiles and any(k in profiles[name] for k in INK_KEYS):
            warns.append(f"{pre} and the hair profile's v1.1 ink fields: slop.ink wins")
        cands = ink_maps(stem, slot, ink)
        found = next((f for f in cands if (ASSETS / f).exists()), None)
        fact = {"width": mode}
        if found is None:
            errors.append(f"{pre}: no ink map (tried {', '.join(cands)}): no ink is drawn")
        else:
            fact["map"] = found
            png = found[: -len(".ktx2")] + ".png" if found.endswith(".ktx2") else found
            if (ASSETS / png).exists():
                try:
                    w, hh, ch, rows = read_png(ASSETS / png)
                except ValueError as e:
                    errors.append(f"{pre}: map {png}: {e}")
                    w = None
                if w:
                    fact["map_size"] = f"{w}x{hh}, {ch} channel(s)"
                    gi = 1 if ch >= 3 else 0
                    on = [(x, y) for y in range(hh) for x in range(w) if rows[y][x * ch + gi] == 0]
                    rs = [rows[y][x * ch] for y in range(hh) for x in range(w) if rows[y][x * ch + gi] < 255]
                    fact["line_texels"] = len(on)
                    if not rs:
                        warns.append(f"{pre}: the map's G is 255 everywhere: no line")
                    elif ch < 3:
                        if mode == "uv" or ink.get("taper"):
                            warns.append(f"{pre}: {'width \"uv\"' if mode == 'uv' else 'taper'} on a greyscale map (no R): " + ("no ink is drawn" if mode == "uv" else "full width"))
                    else:
                        fact["R"] = [min(rs), max(rs)]
                        if max(rs) == 0 and (mode == "uv" or ink.get("taper")):
                            warns.append(f"{pre}: R is 0 wherever there is ink: no line is drawn")
                        if mode == "px" and not ink.get("taper") and min(rs) != max(rs):
                            warns.append(f"{pre}: R varies but \"px\" mode has taper off: the widths are ignored")
                    fact["_on"], fact["_wh"] = on, (w, hh)
            elif not found.endswith(".ktx2"):
                errors.append(f"{pre}: map {found} is not a PNG or KTX2 the audit can read")
        prims = [p for _, p in by_mat.get(i, [])]
        if not prims:
            warns.append(f"{pre}: no primitive uses this material")
        uvs, dens = uv_facts(j, binary, prims)
        for k, u in enumerate(uvs):
            if u is None:
                errors.append(f"{pre}: primitive {k} has no TEXCOORD_0: no ink can be drawn on it")
            elif u[1] <= 1e-12:
                errors.append(f"{pre}: primitive {k}'s TEXCOORD_0 is collapsed (it spans no area): give the strokes a UV island")
            elif u[0] > 0.05:
                warns.append(f"{pre}: {100 * u[0]:.0f}% of primitive {k}'s triangles have no UV area")
        m_uv = dens[len(dens) // 2] if dens else None
        if m_uv:
            fact["m_uv"] = round(m_uv, 5)
            within = sum(1 for d in dens if abs(d - m_uv) <= 0.25 * m_uv) / len(dens)
            fact["density_within_25pct"] = round(within, 3)
            if mode == "uv" and within < 0.9:
                warns.append(f"{pre}: width \"uv\" but only {100 * within:.0f}% of the triangles' texel densities lie within 25% of the median {m_uv:.4f} m/UV: strokes on stretched or scaled islands draw at the wrong width")
            fade = ink.get("fade_px", 3.0) if isinstance(ink.get("fade_px", 3.0), (int, float)) else 3.0
            if r and mode == "px":
                px = ink.get("px", 1.25) if isinstance(ink.get("px", 1.25), (int, float)) else 1.25
                if r * m_uv < px * NEAR_M_PX / 2:
                    warns.append(f"{pre}: range x m_uv is {1000 * r * m_uv:.2f} mm, under px x 4.03 mm = {1000 * px * NEAR_M_PX / 2:.2f} mm: the line is cut flat at its widest")
            if r and mode == "uv" and "R" in fact:
                maxr = fact["R"][1] / 255
                if fade > 0 and maxr > 1 - 1 / fade:
                    warns.append(f"{pre}: the widest stroke's R is {maxr:.2f}, above 1 - 1/fade_px = {1 - 1 / fade:.2f}: its edge is cut flat by the range where the fade lets it show")
                if fade == 0:
                    warns.append(f"{pre}: width \"uv\" with fade_px 0: at a distance the stroke's min_px floor outgrows the range and its edge is cut")
        if "_on" in fact:
            on, (w, hh) = fact.pop("_on"), fact.pop("_wh")
            border = set()
            for p in prims:
                a = p["attributes"]
                if "TEXCOORD_0" not in a or "indices" not in p:
                    continue
                uv, _ = accessor(j, binary, a["TEXCOORD_0"])
                idx = read_indices(j, binary, p["indices"])
                cnt = {}
                for k in range(0, len(idx) - 2, 3):
                    for e in ((idx[k], idx[k + 1]), (idx[k + 1], idx[k + 2]), (idx[k + 2], idx[k])):
                        q = (min(e), max(e))
                        cnt[q] = cnt.get(q, 0) + 1
                for (ea, eb), cc in cnt.items():
                    if cc == 1:
                        steps = int(max(abs(uv[eb][0] - uv[ea][0]) * w, abs(uv[eb][1] - uv[ea][1]) * hh)) + 1
                        for t in range(steps + 1):
                            f = t / steps
                            border.add((int((uv[ea][0] + (uv[eb][0] - uv[ea][0]) * f) * w), int((uv[ea][1] + (uv[eb][1] - uv[ea][1]) * f) * hh)))
            if r and border and on:
                rx, ry = r * w, r * hh
                close = sum(1 for (x, y) in on[:: max(1, len(on) // 400)] if any(((x - bx) / rx) ** 2 + ((y - by) / ry) ** 2 < 1 for bx, by in border))
                if close:
                    warns.append(f"{pre}: centreline texels within range of their UV island's border (about {close} of {min(len(on), 400)} sampled): the line may bleed across it at mips")
        base = m.get("pbrMetallicRoughness", {})
        carrier = base.get("baseColorFactor", [1, 1, 1, 1])[3] == 0 and "baseColorTexture" not in base
        if carrier:
            fact["carrier"] = True
            if m.get("alphaMode") != "BLEND":
                errors.append(f"{pre}: a carrier (alpha 0, no texture) must be BLEND, else it is discarded everywhere ({m.get('alphaMode', 'OPAQUE')})")
            for mi, p in by_mat.get(i, []):
                mesh = j["meshes"][mi]
                names = (mesh.get("extras") or {}).get("targetNames")
                if face_names and not p.get("targets"):
                    warns.append(f"{pre}: a carrier with no morph targets while the face has them: it won't blink with the lid")
                elif face_names and names != face_names and not any(slots.get(q.get("material")) == "face" for q in mesh["primitives"]):
                    warns.append(f"{pre}: a carrier in a separate mesh whose targets are not named as the face's: it won't move with the lid")
        facts.setdefault("ink", {})[name] = fact


# ---- the frame -------------------------------------------------------------------------------

def clips_of(glb):
    j, _ = read_glb(ASSETS / glb)
    return [a.get("name", f"clip{i}") for i, a in enumerate(j.get("animations", []))]


def run_frame(glb, binary, out, also):
    out.mkdir(parents=True, exist_ok=True)
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


def black_copy(glb, slots_wanted):
    """A temporary copy of the file beside it whose `slots_wanted` are black (base colour RGB 0
    with alpha and texture kept, a hair profile's swatches 0, every ink 0), with its sidecars;
    returns its path under the assets (the floor control, docs/HANDMADE_INK.md)."""
    sys.path.insert(0, str(REPO / "living" / "tools"))
    from merge_primitives import write_glb

    j, binary = read_glb(ASSETS / glb)
    for m in j.get("materials", []):
        ms = m.get("extras", {}).get("slop") or {}
        if ms.get("slot") not in slots_wanted:
            continue
        pbr = m.setdefault("pbrMetallicRoughness", {})
        f = pbr.get("baseColorFactor", [1, 1, 1, 1])
        pbr["baseColorFactor"] = [0, 0, 0, f[3]]
        if isinstance(ms.get("hair"), dict):
            for k in SWATCHES:
                ms["hair"][k] = [0, 0, 0]
            if any(k in ms["hair"] for k in INK_KEYS):
                ms["hair"]["ink"] = [0, 0, 0]
        if isinstance(ms.get("ink"), dict):
            ms["ink"]["color"] = [0, 0, 0]
    stem = glb[: -len(".glb")]
    out = stem + "-floor.glb"
    write_glb(ASSETS / out, j, bytearray(binary))
    for f in Path(ASSETS / stem).parent.glob(Path(stem).name + ".*"):
        side = f.name[len(Path(stem).name):]
        if side.endswith((".png", ".ktx2")):
            (ASSETS / (stem + "-floor" + side)).write_bytes(f.read_bytes())
    return out


def floor_slots(t):
    """The slots whose floor a control render must measure (relative patches without a floor)."""
    return {p.get("slot", "hair") for p in t.get("patches", {}).values() if p.get("relative") and not isinstance(p.get("floor"), list)}


def measure(targets_path, shots, profiles, inks=None, floor_shots=None):
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
    floors = {k: read_png(p) for k, p in (floor_shots or {}).items()}
    patches = t.get("patches", {})

    def drawn(p):
        sample = patch_min if p.get("sample") == "min5" else patch_median
        if p.get("target"):
            return list(p["target"])
        if p.get("drawing") and drawing and any(p["drawing"]):
            return sample(drawing, *p["drawing"])
        return None

    rows, suggest = [], {}
    for name, p in patches.items():
        sample = patch_min if p.get("sample") == "min5" else patch_median
        drawing_target = drawn(p)
        if drawing_target is None:
            continue
        ref = patches.get(p["relative"]) if p.get("relative") else None
        if p.get("relative") and (ref is None or drawn(ref) is None):
            print(f"  WARN: patch {name!r}: its reference {p['relative']!r} is missing or has no target; skipped")
            continue
        limit = p.get("tolerance", tol["hair"] if name.lower().startswith("hair") else tol["other"])
        for shot in SHOTS:
            at = p.get(shot)
            if not at or not any(at) or shot not in imgs:
                continue
            got = sample(imgs[shot], *at)
            extra = {}
            target = drawing_target
            if ref is not None:
                # Floor-relative (docs/HANDMADE_INK.md, "Calibration, per slot").
                rat = ref.get(shot)
                if not rat or not any(rat):
                    continue
                rsample = patch_min if ref.get("sample") == "min5" else patch_median
                mref = rsample(imgs[shot], *rat)
                if isinstance(p.get("floor"), list):
                    floor = list(p["floor"])
                elif shot in floors:
                    floor = sample(floors[shot], *at)
                else:
                    continue
                dref = drawn(ref)
                target = [to_srgb(to_linear(f) + to_linear(di) / max(to_linear(dr), 1e-4) * (to_linear(mr) - to_linear(f))) for f, di, dr, mr in zip(floor, drawing_target, dref, mref)]
                extra = dict(floor=floor, reference=p["relative"], reference_measured=mref, drawing_target=drawing_target)
            d = [g - tg for g, tg in zip(got, target)]
            ok = all(abs(x) <= limit for x in d)
            rows.append(dict(patch=name, shot=shot, x=at[0], y=at[1], target=target, measured=got, delta=d, tolerance=limit, passed=ok,
                             luminance=round(luminance(got), 4), target_luminance=round(luminance(target), 4),
                             saturation=round(saturation(got), 4), target_saturation=round(saturation(target), 4), **extra))
            sw = p.get("swatch")
            cur, key = None, sw
            if sw == "ink" and p.get("slot"):
                cands = {n: v for n, v in (inks or {}).items() if v["slot"] == p["slot"] and (not p.get("material") or n == p["material"])}
                if len(cands) == 1:
                    n, v = next(iter(cands.items()))
                    cur, key = v["color"], f"{n}: ink.color"
                elif len(cands) > 1:
                    print(f"  WARN: patch {name!r}: slot {p['slot']!r} has {len(cands)} inked materials; give \"material\"")
            elif sw in SWATCHES + ("ink",) and profiles:
                cur = next(iter(profiles.values())).get(sw)
                key = f"hair.{sw}"
            if cur:
                ratio = [to_linear(tg) / max(to_linear(g), 1e-4) for tg, g in zip(target, got)]
                suggest.setdefault(key, []).append([to_linear(c) * r for c, r in zip(cur, ratio)])
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
        need = floor_slots(json.loads(targets.read_text()))
        floor_shots = None
        if need:
            control = black_copy(glb, need)
            try:
                floor_shots = run_frame(control, binary, out / "floor", a.also)
            finally:
                for f in Path(ASSETS / control[: -len(".glb")]).parent.glob(Path(control).stem + ".*"):
                    f.unlink()
            print(f"  floor control ({', '.join(sorted(need))} black): {out / 'floor'}")
        inks = {}
        j, _ = read_glb(ASSETS / glb)
        for m in j.get("materials", []):
            ms = m.get("extras", {}).get("slop") or {}
            if isinstance(ms.get("ink"), dict) and isinstance(ms["ink"].get("color"), list):
                inks[m.get("name")] = dict(slot=ms.get("slot"), color=ms["ink"]["color"])
        rows, suggested = measure(targets, shots, facts.get("profiles", {}), inks, floor_shots)
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
        print(f"  suggest {k}: {v}")
    passed = not errors and all(r["passed"] for r in rows)
    report = dict(file=glb, out=str(out), audit=dict(errors=errors, warnings=warns, notes=notes, facts=facts), shots={k: str(p) for k, p in shots.items()}, patches=rows, suggested=suggested, passed=passed)
    (out / "report.json").write_text(json.dumps(report, indent=2, default=str))
    print(f"  calibration: {'PASS' if passed else 'FAIL'} ({sum(r['passed'] for r in rows)} of {len(rows)} patches within tolerance; report {out / 'report.json'})")
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
