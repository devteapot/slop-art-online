#!/usr/bin/env python3
"""Caption attention_inside.py's stills and lay out E1b's contact sheets (ImageMagick).

  attention_inside_sheet.py OUT_DIR STILLS_JSON...

`contact-sheet.png`: rows N 10, N 16, N 32, full view; columns centre-Middle, centre-Far,
edge-Middle, edge-Far. `picks-sheet.png`: the Middle stills with the pick rings (green: the
authority's `far_cap` pick; orange: v2's order would attend and the authority did not). Each still,
captioned, with its JSON, in OUT_DIR; the uncaptioned ones in `raw/`.
"""
import json, os, shutil, subprocess, sys

out = sys.argv[1]
os.makedirs(os.path.join(out, "raw"), exist_ok=True)
BOLD = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
REG = "/System/Library/Fonts/Supplemental/Arial.ttf"
shots = {}
for path in sys.argv[2:]:
    d = json.load(open(path))
    base = os.path.dirname(path)
    for s in d["shots"]:
        s["_dir"] = base
        s["_run"] = {k: d["run"].get(k) for k in ("run", "db", "me", "site", "square_m", "relocated", "centre_at", "edge_at", "module", "client_exit", "stances_before", "stances_after")}
        s["_timeline"] = d["run"].get("alive_timeline")
        shots[s["still"][:-4]] = s


def caption(src, dst, line1, line2, colour):
    subprocess.run(["magick", src, "-gravity", "north", "-background", "#111", "-splice", "0x100", "-font", BOLD, "-fill", colour, "-pointsize", "46",
                    "-annotate", "+0+6", line1, "-font", REG, "-fill", "#ddd", "-pointsize", "29", "-annotate", "+0+60", line2,
                    "-bordercolor", "#111", "-border", "6", dst], check=True)


def tile(key, picks=False):
    name = f"{key}-picks" if picks else key
    dst = os.path.join(out, f"{name}.png")
    s = shots.get(key)
    src = os.path.join(s["_dir"], f"{name}.png") if s else None
    if not s or not os.path.exists(src):
        subprocess.run(["magick", "-size", "1920x1080", "xc:#222", "-fill", "white", "-pointsize", "60", "-gravity", "center", "-annotate", "0", f"missing: {name}", dst], check=True)
        return dst
    n = "full view" if not s["attended_n"] else f"N = {s['attended_n']} + crowd figures, 6 m"
    line1 = f"{n} · {s['position']} · {s['zoom_stop'].capitalize()}" + (" · picks" if picks else "")
    crowd = f" · crowd {s['crowd_members']} in {s['crowd_cells']} cells" if s["attended_n"] else ""
    line2 = (f"perceived {s['perceived']} ({s['perceived_fighters']} fighters, {s['others_perceived']} others){crowd} · "
             f"alive {s['fighters_alive']}, fallen {s['fighters_dead']} · battle {s['battle_s']:.0f} s · frame p50 {s['frame_ms_p50']} ms")
    if picks:
        line2 = (f"green: the authority's {s['perceived']} (nearest) · orange: v2's order would add {len(s['v2_only'] or [])} · "
                 f"agree {s['picks_agree']} of {s['attended_n']}")
    caption(src, dst, line1, line2, "#ff9a6a" if s["attended_n"] else "white")
    shutil.copy(src, os.path.join(out, "raw", f"{name}.png"))
    if not picks:
        meta = {k: v for k, v in s.items() if not k.startswith("_")}
        meta.update(run=s["_run"], alive_timeline=s["_timeline"], raw_still=f"raw/{name}.png", evidence_dir=s["_dir"])
        json.dump(meta, open(os.path.join(out, f"{key}.json"), "w"), indent=1)
    return dst


COLS = [("centre", "middle"), ("centre", "far"), ("edge", "middle"), ("edge", "far")]
tiles = [tile(f"{p}-{z}-{arm}") for arm in ("n10", "n16", "n32", "full") for p, z in COLS]
sheet = os.path.join(out, "contact-sheet.png")
subprocess.run(["magick", "montage", "-font", REG, *tiles, "-tile", "4x", "-geometry", "800x+6+6", "-background", "#000", "-depth", "8", sheet], check=True)
title = "Attention E1b · player inside a 200-fighter battle (Cullet, flat plaza) · columns: centre Middle, centre Far, edge Middle, edge Far · rows N 10, 16, 32, full"
subprocess.run(["magick", sheet, "-gravity", "north", "-background", "#000", "-splice", "0x60", "-font", BOLD, "-fill", "white", "-pointsize", "34",
                "-annotate", "+0+12", title, "-depth", "8", sheet], check=True)
ptiles = [tile(f"{p}-middle-{arm}", picks=True) for arm in ("n10", "n16", "n32") for p in ("centre", "edge")]
psheet = os.path.join(out, "picks-sheet.png")
subprocess.run(["magick", "montage", "-font", REG, *ptiles, "-tile", "2x", "-geometry", "960x+6+6", "-background", "#000", "-depth", "8", psheet], check=True)
subprocess.run(["magick", psheet, "-gravity", "north", "-background", "#000", "-splice", "0x56", "-font", BOLD, "-fill", "white", "-pointsize", "30",
                "-annotate", "+0+12", "E1b picks · green: far_cap (engaged with me, then nearest) · orange: v2 order (fighting nearest first) adds", "-depth", "8", psheet], check=True)
print(sheet, psheet)
