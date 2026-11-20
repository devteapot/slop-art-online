#!/usr/bin/env python3
"""Label battle_stills.py's stills and lay them out as one contact sheet (ImageMagick `magick`).

  battle_stills_sheet.py RESULTS_JSON OUT_DIR

Each still gets a caption bar (`far_cap 25 · Middle · 25 of 200 seen`, MOCK in red for the crowd
mock) and is copied to OUT_DIR as `<row>-<stop>.png`; `contact-sheet.png` holds them in a grid,
rows off / 40 / 25 / 40 + mock / 25 + mock, columns Middle and Far.
"""
import json, os, subprocess, sys

res = json.load(open(sys.argv[1]))
out = sys.argv[2]
os.makedirs(out, exist_ok=True)
ROWS = [("real", "off"), ("real", "40"), ("real", "25"), ("mock", "40"), ("mock", "25")]
STOPS = [("middle", "Middle (12 m)"), ("far", "Far (19 m)")]
by = {(s["kind"], s["far_cap"], s["stop"]): s for s in res["stills"]}
tiles = []
for kind, cap in ROWS:
    for stop, stop_name in STOPS:
        s = by.get((kind, cap, stop))
        name = f"{'mock-' if kind == 'mock' else ''}far_cap-{cap}-{stop}.png"
        dst = os.path.join(out, name)
        if not s or not os.path.exists(s["png"]):
            subprocess.run(["magick", "-size", "1600x980", "xc:#222", "-fill", "white", "-pointsize", "40", "-gravity", "center", "-annotate", "0", f"missing: {kind} {cap} {stop}", dst], check=True)
            tiles.append(dst)
            continue
        seen = s["perceived_fighters"]
        cap_txt = "far_cap off" if cap == "off" else f"far_cap {cap}"
        line1 = f"{cap_txt} · {stop_name.split(' ')[0]} · {seen} of {s['battle_alive']} seen"
        fm = s["frame_ms"]
        line2 = (f"perceived {s['perceived']} (fighters {seen}), drawn {s['drawn']} · frame p50 {fm['p50']:.1f} ms p90 {fm['p90']:.1f} ms"
                 if fm.get("p50") is not None else f"perceived {s['perceived']}, drawn {s['drawn']}")
        if kind == "mock":
            line1 = "MOCK crowd · " + line1
            line2 += f" · {s.get('impostors') or 0} impostors"
        colour = "#ff5a4a" if kind == "mock" else "white"
        subprocess.run(["magick", s["png"], "-gravity", "north", "-background", "#111", "-splice", "0x80",
                        "-font", "/System/Library/Fonts/Supplemental/Arial Bold.ttf", "-fill", colour, "-pointsize", "38", "-annotate", "+0+6", line1,
                        "-font", "/System/Library/Fonts/Supplemental/Arial.ttf", "-fill", "#ccc", "-pointsize", "24", "-annotate", "+0+50", line2,
                        *(["-bordercolor", "#ff5a4a", "-border", "6"] if kind == "mock" else ["-bordercolor", "#111", "-border", "6"]),
                        dst], check=True)
        tiles.append(dst)
sheet = os.path.join(out, "contact-sheet.png")
title = f"far_cap · {res['fighters']}-fighter battle · left Middle (12 m), right Far (19 m)"
subprocess.run(["magick", "montage", "-font", "/System/Library/Fonts/Supplemental/Arial.ttf", *tiles, "-tile", "2x", "-geometry", "800x+8+8",
                "-background", "#000", "-fill", "white", "-pointsize", "22", "-title", title, "-depth", "8", sheet], check=True)
print(sheet)
