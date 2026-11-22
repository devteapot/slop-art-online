#!/usr/bin/env python3
"""Label attention_stills.py's stills and lay them out as one contact sheet (ImageMagick).

  attention_sheet.py OUT_DIR STILLS_JSON...

Copies each still and its JSON (one per shot) to OUT_DIR, captioned: the arm, the mode and cell,
the zoom stop, the attended N and how many were perceived, the crowd mock's members and cells, the
fighters alive, the residents in sight and the frame time. `contact-sheet.png` holds them in rows
(the full-view reference, N 16 and 32 × figures or discs × 6 or 4 m, then no-crowd rows for
comparison), columns Middle and Far.
"""
import json, os, shutil, subprocess, sys

out = sys.argv[1]
os.makedirs(out, exist_ok=True)
shots = {}
for path in sys.argv[2:]:
    d = json.load(open(path))
    base = os.path.dirname(path)
    for s in d["shots"]:
        s["_png"] = os.path.join(base, s["still"])
        s["_run"] = {k: d["run"].get(k) for k in ("run", "db", "me", "centre", "player_at", "south_m", "fighters_spawned", "sides", "module", "far_cap_own_before", "client_exit")}
        shots[s["still"][:-4]] = s

ROWS = [("noff", "full", None), ("n16", "figures", 6), ("n16", "figures", 4), ("n16", "discs", 6), ("n16", "discs", 4),
        ("n32", "figures", 6), ("n32", "figures", 4), ("n32", "discs", 6), ("n32", "discs", 4),
        ("n16", "nocrowd", None), ("n32", "nocrowd", None)]
BOLD = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
REG = "/System/Library/Fonts/Supplemental/Arial.ttf"
tiles = []
for arm, mode, cell in ROWS:
    for stop in ("middle", "far"):
        key = f"{stop}-{arm}-{mode}" + (f"-{cell}m" if cell else "")
        dst = os.path.join(out, f"{key}.png")
        s = shots.get(key)
        if not s or not os.path.exists(s["_png"]):
            subprocess.run(["magick", "-size", "1920x1080", "xc:#222", "-fill", "white", "-pointsize", "60", "-gravity", "center", "-annotate", "0", f"missing: {key}", dst], check=True)
            tiles.append(dst)
            continue
        n = "full view (no cap)" if arm == "noff" else f"N = {arm[1:]}"
        what = {"full": "everyone individual", "nocrowd": "no crowd (comparison)", "figures": f"+ crowd figures, {cell} m cells", "discs": f"+ crowd discs, {cell} m cells"}[mode]
        line1 = f"{n} {what} · {stop.capitalize()}"
        crowd = f" · crowd {s['crowd_members']} in {s['crowd_cells']} cells" if mode in ("figures", "discs") else ""
        line2 = (f"perceived {s['perceived']} ({s['perceived_fighters']} fighters, {s['others_perceived']} others){crowd} · "
                 f"in field {s['in_field']} · fighters alive {s['fighters_alive']} · frame p50 {s['frame_ms_p50']} ms")
        colour = "#ff7a5a" if mode in ("figures", "discs") else "white"
        subprocess.run(["magick", s["_png"], "-gravity", "north", "-background", "#111", "-splice", "0x96",
                        "-font", BOLD, "-fill", colour, "-pointsize", "44", "-annotate", "+0+6", line1,
                        "-font", REG, "-fill", "#ddd", "-pointsize", "28", "-annotate", "+0+58", line2,
                        "-bordercolor", "#111", "-border", "6", dst], check=True)
        meta = {k: v for k, v in s.items() if not k.startswith("_")}
        meta["run"] = s["_run"]
        meta["still"] = os.path.basename(dst)
        os.makedirs(os.path.join(out, "raw"), exist_ok=True)
        shutil.copy(s["_png"], os.path.join(out, "raw", os.path.basename(dst)))
        meta["raw_still"] = os.path.join("raw", os.path.basename(dst))
        meta["evidence_dir"] = os.path.dirname(s["_png"])
        json.dump(meta, open(os.path.join(out, f"{key}.json"), "w"), indent=1)
        tiles.append(dst)
sheet = os.path.join(out, "contact-sheet.png")
title = "Attention E1 · 200 fighters, Cullet · player 26 m south, facing north · left Middle, right Far · mock crowd rows in orange"
subprocess.run(["magick", "montage", "-font", REG, *tiles, "-tile", "2x", "-geometry", "960x+8+8", "-background", "#000", "-depth", "8", sheet], check=True)
subprocess.run(["magick", sheet, "-gravity", "north", "-background", "#000", "-splice", "0x56", "-font", BOLD, "-fill", "white", "-pointsize", "30",
                "-annotate", "+0+12", title, "-depth", "8", sheet], check=True)
print(sheet)
