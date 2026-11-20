"""The contract audit for composed files and the shared pages (contract v1.3,
docs/HANDMADE_COMPOSED.md, "The audit and tools"), used by `calibrate.py`:

    python3 living/tools/characters/calibrate.py lookdev/types/adult-f-a.glb --no-run
    python3 living/tools/characters/calibrate.py --pages lookdev [--no-run]

A composed file (a type or style file) opts in by its scene's `slop` with a `contract` and no
`character`. Its materials' kinds stay the name rule's; the audit checks each `slop.hair`
(swatches, thresholds, `palette`, `ref`, anchors, `ink_m_uv` against the measured density, the
mask), each `slop.ink` (v1.2's checks, `ref`, `m_uv`), and prints the palette's entries for the
nine hair colours. `--pages` checks the hair-mask and ink pages against their manifests. Plain
Python.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import palette  # noqa: E402

RGB_OK = lambda v: isinstance(v, list) and len(v) == 3 and all(isinstance(x, int) and not isinstance(x, bool) and 0 <= x <= 255 for x in v)  # noqa: E731


def is_composed(slop):
    return isinstance(slop, dict) and "character" not in slop and "contract" in slop


def name_kind(name):
    """The client's name rule for a composed material (compose.rs `kind_of`), as a slot-like word."""
    skin = name.endswith("_SKIN") or "Skin" in name
    if "_HAIR" in name:
        return "hair"
    if skin and "Face" in name:
        return "face"
    if skin:
        return "skin"
    if "_FACE" in name or "_EYE" in name:
        return "eyes"
    return "cloth"


def takes_tag(name):
    """Whether a material's name takes one of the person's colours (characters.rs `slot`)."""
    return any(k in name for k in ("_HAIR", "FaceBrow", "_SKIN", "EyeIris", "_CLOTH"))


def median_density(cal, j, binary, prims):
    _, dens = cal.uv_facts(j, binary, prims)
    return dens[len(dens) // 2] if dens else None


def palette_checks(name, h, errors, warns, facts):
    pre = f"material {name!r}: hair"
    pal = h.get("palette", "fixed")
    if pal not in ("fixed", "tag"):
        errors.append(f"{pre}.palette is {pal!r}, not \"fixed\" or \"tag\" (drawn fixed)")
        return
    if pal == "fixed":
        for k in ("ref", "anchors"):
            if k in h:
                warns.append(f"{pre}.{k} with a fixed palette does nothing")
        return
    if not RGB_OK(h.get("ref")):
        errors.append(f"{pre}.ref is {h.get('ref')!r}, not three integers 0-255 (drawn fixed)")
        return
    if palette.oklab(h["ref"])[0] < 0.05:
        errors.append(f"{pre}.ref {h['ref']} is too dark (OKLab L under 0.05; drawn fixed)")
        return
    anchors = h.get("anchors", [])
    if not isinstance(anchors, list):
        errors.append(f"{pre}.anchors is not a list (ignored)")
        anchors = []
    if len(anchors) > 4:
        errors.append(f"{pre}: {len(anchors)} anchors; at most 4 (the rest are dropped)")
    good = []
    for i, a in enumerate(anchors[:4]):
        bad = [k for k in ("ref", "shade", "mid", "light", "highlight") if not RGB_OK(a.get(k) if isinstance(a, dict) else None)]
        if bad:
            errors.append(f"{pre}.anchors[{i}]: {', '.join(bad)} not three integers 0-255 (the anchor is dropped)")
        elif palette.oklab(a["ref"])[0] < 0.05:
            errors.append(f"{pre}.anchors[{i}].ref is too dark (the anchor is dropped)")
        else:
            good.append(a)
    prof = dict(h, anchors=good)
    if not all(RGB_OK(h.get(k)) for k in palette.ROWS[:4]):
        return
    for ref, sw, ink in palette.anchors_of(prof):
        for k, s in zip(palette.ROWS, list(sw) + ([ink] if ink else [])):
            if palette.clamped(ref, s):
                warns.append(f"{pre}: {k} {list(s)} against ref {list(ref)}: a ratio is clamped at {palette.MAX_RATIO}")
            dh = palette.ratios(ref, s)[2]
            if abs(dh) > 30:
                warns.append(f"{pre}: {k} {list(s)} is {dh:+.0f}° in hue from ref {list(ref)}: more than 30°")
    table = {}
    for cname, hx in palette.HAIR_COLOURS.items():
        rows, red = palette.entry(palette.anchors_of(prof), palette.hexed(hx))
        table[cname] = {k: list(c) for k, c in zip(palette.ROWS, rows)}
        if red:
            table[cname]["gamut"] = red
    facts.setdefault("palette", {})[name] = table


def composed_audit(cal, glb, j, binary, stem, slop):
    """(errors, warnings, notes, facts) of an opted-in composed file."""
    errors, warns, notes, facts = [], [], [], {}
    if slop.get("contract") != 1:
        errors.append(f"scene: slop.contract is {slop.get('contract')!r}, not 1 (the file's slop is ignored)")
    facts["composed"] = True
    mats = j.get("materials", [])
    slots, profiles = {}, {}
    by_mat = {}
    for mi, mesh in enumerate(j.get("meshes", [])):
        for p in mesh.get("primitives", []):
            by_mat.setdefault(p.get("material"), []).append(p)
    nodes_by_mat = {}
    for node in j.get("nodes", []):
        if "mesh" in node:
            for p in j["meshes"][node["mesh"]]["primitives"]:
                nodes_by_mat.setdefault(p.get("material"), set()).add(node.get("name", ""))
    for i, m in enumerate(mats):
        name = m.get("name", f"material {i}")
        ms = (m.get("extras") or {}).get("slop")
        if not ms:
            continue
        s = ms.get("slot")
        if s is None:
            if "hair" in ms or ("ink" in ms and not isinstance((ms.get("ink") or {}).get("map"), str)):
                warns.append(f"material {name!r}: slop without a slot")
        elif s not in cal.SLOTS:
            errors.append(f"material {name!r}: slot {s!r} is not one of {sorted(cal.SLOTS)}")
            continue
        else:
            slots[i] = s
            nk = name_kind(name)
            if s != nk and not (s == "face" and nk == "skin") and not (s == "tint" and nk == "eyes"):
                warns.append(f"material {name!r}: slot {s!r}, but the name rule draws it as {nk!r} (the name decides on composed files)")
        if "hair" in ms:
            h = ms["hair"]
            if s != "hair" or name_kind(name) != "hair":
                errors.append(f"material {name!r}: a hair profile on a material the name rule doesn't draw as hair (ignored)")
                continue
            for k in cal.SWATCHES:
                if not RGB_OK(h.get(k)):
                    errors.append(f"material {name!r}: hair.{k} is {h.get(k)!r}, not three integers 0-255 (the profile is ignored)")
            t1, t2 = h.get("t1", -0.2), h.get("t2", 0.4)
            if isinstance(t1, (int, float)) and isinstance(t2, (int, float)) and t2 <= t1:
                errors.append(f"material {name!r}: hair.t2 {t2} is not above t1 {t1} (the profile is ignored)")
            for k in sorted(set(h) - cal.HAIR_KEYS):
                warns.append(f"material {name!r}: hair.{k} is not a contract key (ignored)")
            palette_checks(name, h, errors, warns, facts)
            profiles[name] = h
            prims = by_mat.get(i, [])
            if any("_RING" in p["attributes"] for p in prims):
                warns.append(f"material {name!r}: _RING on profile hair is ignored (a profile has no ring)")
            if not any(n.startswith("Far") for n in nodes_by_mat.get(i, ())) and any(n.startswith("FarHair") for n in (x.get("name", "") for x in j.get("nodes", []))):
                warns.append(f"material {name!r}: the file's FarHair wears another material: the colours change at the far switch")
            mask = None
            for cand in ([h["highlight_map"]] if isinstance(h.get("highlight_map"), str) else []) + [stem + ".hair.png"]:
                for f in (cand[:-4] + ".ktx2", cand):
                    if (cal.ASSETS / f).exists():
                        mask = mask or f
            facts.setdefault("masks", {})[name] = mask
            if mask is None and not any("_HIGHLIGHT" in p["attributes"] for p in prims):
                warns.append(f"material {name!r}: a hair profile without _HIGHLIGHT or a mask texture: three bands, no highlight")
            if "ink_m_uv" in h:
                d = h["ink_m_uv"]
                meas = median_density(cal, j, binary, prims)
                if not isinstance(d, (int, float)) or d <= 0:
                    errors.append(f"material {name!r}: hair.ink_m_uv is {d!r}, not a number above 0 (measured instead)")
                elif meas and abs(meas - d) > 0.1 * d:
                    warns.append(f"material {name!r}: hair.ink_m_uv {d} but the hair measures {meas:.4f} m/UV (over 10% off): the lock lines' fade is off by as much")
                facts.setdefault("hair_m_uv", {})[name] = {"declared": d, "measured": round(meas, 4) if meas else None}
    # v1.2's ink checks, with v1.3's keys.
    cal.ink_audit(j, binary, stem, mats, slots, profiles, errors, warns, facts)
    for i, m in enumerate(mats):
        ink = ((m.get("extras") or {}).get("slop") or {}).get("ink")
        if not isinstance(ink, dict):
            continue
        name = m.get("name", f"material {i}")
        if "ref" in ink:
            if not RGB_OK(ink["ref"]):
                errors.append(f"material {name!r}: ink.ref is {ink['ref']!r}, not three integers 0-255 (the ink is ignored)")
            elif not takes_tag(name):
                warns.append(f"material {name!r}: ink.ref, but the name takes none of the person's colours: the colour is drawn as it is")
        if "m_uv" in ink:
            d = ink["m_uv"]
            meas = (facts.get("ink", {}).get(name) or {}).get("m_uv")
            if not isinstance(d, (int, float)) or d <= 0:
                errors.append(f"material {name!r}: ink.m_uv is {d!r}, not a number above 0 (the ink is ignored)")
            elif meas and abs(meas - d) > 0.1 * d:
                warns.append(f"material {name!r}: ink.m_uv {d} but the strokes measure {meas} m/UV (over 10% off): widths and the fade are off by as much")
    return errors, warns, notes, facts


def uv_of(cal, j, binary, mat_names):
    """Every TEXCOORD_0 of the primitives whose material is in `mat_names`, by material name, as
    lists of (u, v) in primitive order."""
    names = {i: m.get("name") for i, m in enumerate(j.get("materials", []))}
    out = {}
    for mesh in j.get("meshes", []):
        for p in mesh.get("primitives", []):
            n = names.get(p.get("material"))
            if n in mat_names and "TEXCOORD_0" in p["attributes"]:
                uv, _ = cal.accessor(j, binary, p["attributes"]["TEXCOORD_0"])
                out.setdefault(n, []).append(uv or [])
    return out


def pages(cal, lookdev):
    """(errors, warnings, facts) of the shared pages against their manifests."""
    errors, warns, facts = [], [], {}
    root = cal.ASSETS / lookdev
    # The hair-mask page.
    hm = root / "styles" / "hair" / "hair-masks.json"
    if hm.exists():
        top = json.loads(hm.read_text())
        size, cell = top.get("size", 4096), top.get("cell", 512)
        # One page, or several (`pages`: each its own page and files, the first the manifest's
        # own); every page is audited alike, each with its one profile.
        facts["hair_page"] = []
        for man in top.get("pages") or [top]:
            if not (cal.ASSETS / man.get("page", "")).exists() and not (cal.ASSETS / (man.get("page", "")[:-4] + ".ktx2")).exists():
                errors.append(f"hair page {man.get('page')!r} is not on disk: every cut's mask is missing")
            rects, profile, uvs = {}, None, {}
            for f, (c, r, w, h) in sorted(man.get("files", {}).items()):
                path = root / "styles" / "hair" / f
                if not path.exists():
                    errors.append(f"hair page: {f} is listed but not on disk")
                    continue
                j, binary = cal.read_glb(path)
                sc = j.get("scenes", [{}])[j.get("scene", 0)].get("extras", {}).get("slop")
                if not is_composed(sc):
                    errors.append(f"hair page: {f} does not opt in (its scene has no slop contract)")
                hair = [m for m in j.get("materials", []) if "_HAIR" in m.get("name", "")]
                ms = [((m.get("extras") or {}).get("slop") or {}).get("hair") for m in hair]
                for p in ms:
                    if p is None:
                        errors.append(f"hair page: {f}'s hair has no profile")
                        continue
                    if p.get("highlight_map") != man.get("page"):
                        errors.append(f"hair page: {f} names {p.get('highlight_map')!r}, not the page")
                    if profile is None:
                        profile = p
                    elif p != profile:
                        errors.append(f"hair page: {f}'s profile differs from the page's first (it would be a material of its own)")
                uv = uv_of(cal, j, binary, {m.get("name") for m in hair})
                flat = [q for lst in uv.values() for prim in lst for q in prim]
                x0, y0, x1, y1 = c * cell / size, r * cell / size, (c + w) * cell / size, (r + h) * cell / size
                half = 0.5 / size
                out = sum(1 for (u, v) in flat if not (x0 - half <= u <= x1 + half and y0 - half <= v <= y1 + half))
                if out:
                    errors.append(f"hair page: {f}: {out} of {len(flat)} hair UVs outside its rectangle {[c, r, w, h]}")
                rects[f] = (c, r, w, h)
                uvs[f] = flat
                prims = [p for mesh in j["meshes"] for p in mesh["primitives"] if j["materials"][p["material"]].get("name", "").endswith("_HAIR")]
                meas = median_density(cal, j, binary, prims)
                decl = (profile or {}).get("ink_m_uv")
                if meas and decl and abs(meas - decl) > 0.1 * decl:
                    warns.append(f"hair page: {f} measures {meas:.3f} m/UV against the page's {decl} (over 10%)")
            keys = sorted(rects)
            for i, a in enumerate(keys):
                for b in keys[i + 1:]:
                    ra, rb = rects[a], rects[b]
                    if ra[0] < rb[0] + rb[2] and rb[0] < ra[0] + ra[2] and ra[1] < rb[1] + rb[3] and rb[1] < ra[1] + ra[3]:
                        if uvs[a] != uvs[b]:
                            errors.append(f"hair page: {a} and {b} overlap and their hair differs")
            # v1.3.1 `strands`: a boolean; when on, the page's B is the strands, 0.5 (128)
            # neutral, so no texel may be 0 (a dark fringe at every island's edge).
            strands = (profile or {}).get("strands", False)
            if not isinstance(strands, bool):
                errors.append(f"hair page {man.get('page')!r}: strands {strands!r} is not true or false (no strands are drawn)")
            elif strands:
                try:
                    from PIL import Image
                    import numpy as np
                    bch = np.asarray(Image.open(cal.ASSETS / man.get("page", "")).convert("RGB"))[..., 2]
                    zero = int((bch == 0).sum())
                    if zero:
                        errors.append(f"hair page {man.get('page')!r}: strands on, but {zero} texels of B are 0 (2 x B blacks them out; fill 128 where there are no strands)")
                except (OSError, ImportError) as e:
                    warns.append(f"hair page {man.get('page')!r}: strands on, B not read ({e})")
            facts["hair_page"].append({"page": man.get("page"), "files": len(rects), "cells_used": len({rects[k] for k in rects}), "strands": strands})
    else:
        facts["hair_page"] = "no hair-masks.json"
    # The ink page.
    im = root / "types" / "types.ink.json"
    if im.exists():
        man = json.loads(im.read_text())
        size, cell = man.get("size", 4096), man.get("cell", 1024)
        for slot, page in man.get("pages", {}).items():
            if not (cal.ASSETS / page).exists() and not (cal.ASSETS / (page[:-4] + ".ktx2")).exists():
                errors.append(f"ink page {page!r} ({slot}) is not on disk: every carrier would draw nothing")
        by_class, inks = {}, {}
        for path in sorted((root / "types").glob("*.glb")):
            t = path.stem
            j, binary = cal.read_glb(path)
            sc = j.get("scenes", [{}])[j.get("scene", 0)].get("extras", {}).get("slop")
            inked = {m.get("name"): m["extras"]["slop"]["ink"] for m in j.get("materials", []) if isinstance(((m.get("extras") or {}).get("slop") or {}).get("ink"), dict)}
            if not inked:
                continue
            if not is_composed(sc):
                errors.append(f"ink page: {t} carries ink but does not opt in")
            cls = t.rsplit("-", 1)[0]
            cellpos = man.get("types", {}).get(t) or man.get("classes", {}).get(cls)
            if cellpos is None:
                errors.append(f"ink page: {t}'s class {cls} has no cell in the manifest")
                continue
            for n, ink in inked.items():
                if ink.get("map") not in man.get("pages", {}).values():
                    warns.append(f"ink page: {t} {n} names {ink.get('map')!r}, not a page (its own material)")
                if n in inks and inks[n] != ink:
                    errors.append(f"ink page: {t} {n}'s ink differs from another type's (it would be a material of its own)")
                inks.setdefault(n, ink)
            uv = uv_of(cal, j, binary, set(inked))
            c, r = cellpos
            x0, y0, x1, y1 = c * cell / size, r * cell / size, (c + 1) * cell / size, (r + 1) * cell / size
            flat = [q for lst in uv.values() for prim in lst for q in prim]
            out = sum(1 for (u, v) in flat if not (x0 <= u <= x1 and y0 <= v <= y1))
            if out:
                errors.append(f"ink page: {t}: {out} of {len(flat)} carrier UVs outside its class's cell {cellpos}")
            by_class.setdefault(cls, []).append((t, uv))
        same = {}
        for cls, members in sorted(by_class.items()):
            first_t, first = members[0]
            diff = []
            for t, uv in members[1:]:
                ok = sorted(uv) == sorted(first) and all(len(a) == len(b) and all(abs(p[0] - q[0]) <= 0.5 / size and abs(p[1] - q[1]) <= 0.5 / size for p, q in zip(a, b)) for k in uv for a, b in zip(uv[k], first.get(k, [])))
                if not ok:
                    diff.append(t)
            same[cls] = not diff
            if diff:
                errors.append(f"ink page: class {cls}: {', '.join(diff)} carry other TEXCOORD_0 than {first_t}: the class's types must share one layout")
        facts["ink_page"] = {"pages": man.get("pages"), "classes": same, "carrier_materials": sorted(inks)}
    else:
        facts["ink_page"] = "no types.ink.json"
    return errors, warns, facts
