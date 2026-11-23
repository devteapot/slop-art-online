#!/usr/bin/env python3
"""Known-answer test of the measuring view (`LIVING_GAME_VIEW_ORTHO=1`, docs/char-port-2/measure-view/README.md):
a head of known size (ortho_shape.py) drawn through the real client, its widths read back in metres
from the pixels and the recorded pixels per metre.

    python3 living/tools/characters/ortho_selftest.py [--binary BIN] [--out DIR] [--no-portrait]

BIN defaults to $LIVING_GAME_BIN, else `$CARGO_TARGET_DIR/release/living-game`, else
living/target/release/living-game; it must be built from this checkout (the client reads its assets from the
checkout it was built in), since the subject is written to `living/game/assets/measure/ortho_head.glb` (git-ignored).
DIR defaults to a fresh temporary folder. Five client runs,
each in the bind pose (`LIVING_GAME_VIEW_CLIP=bind`), each photograph with its plate (the same
view without the model, `LIVING_GAME_VIEW_PLATE=1`):

- **lines:** the measuring view as in play, the outline and the finishing pass's ink on, front and
  side (`LIVING_GAME_VIEW_ORTHO_M` 0.30 m, 3000 px/m at 1600x900, the frame's middle at the head's);
- **no outline:** the same with `LIVING_GAME_PERF=nooutlines`;
- **bare:** `nooutlines,noedges`: neither the outline nor the ink;
- **portrait:** the old perspective front portrait `0:8:0.36:0.88` (the camera 8° up) and
  `0:0:0.36:0.88` (level), lines on, as S6/S7 measured.

**The measure.** A pixel is the model's where it differs from its plate by more than half the
contrast of the model's own pixels against it (the edge's 50% crossing, so an anti-aliased edge
counts half a pixel either way). The head's width is read on the row of its equator (row from
`ground_row_px − y · px_per_m`), its depth on the same row from the side, its top on the middle
column; the eyes are the centroids of the dark pixels (the eyes' material) left and right of the
middle.

**The acceptance** (exit 1 on any failure):
- bare: the width, the depth and the head's top each within 1% of the known (the top: of the head's height);
- lines: the width and depth within 1%, and the outline's and ink's pixels reported apart;
- every ortho run: the eye spacing within 1%, and the sidecar's pixels per metre exactly the frame's
  height in pixels over `LIVING_GAME_VIEW_ORTHO_M`.
The portrait is reported, not held: how far the width over the eye spacing reads from the known
2.344 (the perspective and the pitch).

Plain Python (stdlib only). Writes DIR/selftest.json.
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path[:0] = [str(HERE)]
import ortho_shape  # noqa: E402

SIZE = (1600, 900)
FRAME_M = 0.30
TOL = 0.01


def read_png(path):
    """(width, height, rows of RGB tuples' flat bytes): 8-bit RGB or RGBA, not interlaced."""
    b = Path(path).read_bytes()
    assert b[:8] == b"\x89PNG\r\n\x1a\n", path
    i, idat, hdr = 8, bytearray(), None
    while i < len(b):
        n = int.from_bytes(b[i:i + 4], "big")
        kind, data = b[i + 4:i + 8], b[i + 8:i + 8 + n]
        if kind == b"IHDR":
            hdr = data
        elif kind == b"IDAT":
            idat += data
        i += 12 + n
    w, h = int.from_bytes(hdr[0:4], "big"), int.from_bytes(hdr[4:8], "big")
    depth, ctype, interlace = hdr[8], hdr[9], hdr[12]
    assert depth == 8 and ctype in (2, 6) and interlace == 0, (path, depth, ctype, interlace)
    bpp = 3 if ctype == 2 else 4
    raw = zlib.decompress(bytes(idat))
    stride = w * bpp
    rows, prev = [], bytearray(stride)
    for r in range(h):
        f = raw[r * (stride + 1)]
        line = bytearray(raw[r * (stride + 1) + 1:(r + 1) * (stride + 1)])
        if f == 1:
            for x in range(bpp, stride):
                line[x] = (line[x] + line[x - bpp]) & 255
        elif f == 2:
            for x in range(stride):
                line[x] = (line[x] + prev[x]) & 255
        elif f == 3:
            for x in range(stride):
                left = line[x - bpp] if x >= bpp else 0
                line[x] = (line[x] + ((left + prev[x]) >> 1)) & 255
        elif f == 4:
            for x in range(stride):
                a = line[x - bpp] if x >= bpp else 0
                c = prev[x - bpp] if x >= bpp else 0
                bb = prev[x]
                p = a + bb - c
                pa, pb, pc = abs(p - a), abs(p - bb), abs(p - c)
                line[x] = (line[x] + (a if pa <= pb and pa <= pc else bb if pb <= pc else c)) & 255
        rows.append(bytes(line) if bpp == 3 else bytes(v for k, v in enumerate(line) if k % 4 != 3))
        prev = line
    return w, h, rows


class Picture:
    def __init__(self, png):
        self.w, self.h, self.rows = read_png(png)
        _, _, self.plate = read_png(str(png).replace(".png", ".plate.png"))

    def px(self, x, y):
        r = self.rows[y]
        return r[3 * x], r[3 * x + 1], r[3 * x + 2]

    def diff(self, x, y):
        a, p = self.rows[y], self.plate[y]
        return max(abs(a[3 * x + k] - p[3 * x + k]) for k in range(3))

    def run(self, line, horizontal=True):
        """The model's extent along a row (or a column): (first, last) pixel at the 50% crossing,
        and the edge widths (pixels from the first faint difference to the crossing)."""
        n = self.w if horizontal else self.h
        d = [self.diff(i, line) if horizontal else self.diff(line, i) for i in range(n)]
        lit = [i for i, v in enumerate(d) if v > 8]
        if not lit:
            return None
        lo, hi = lit[0], lit[-1]
        # The model's own contrast: the middle half of its run.
        inner = sorted(d[lo + (hi - lo) // 4: hi - (hi - lo) // 4 + 1])
        ref = inner[len(inner) // 2]
        on = [i for i in range(lo, hi + 1) if d[i] > ref / 2]
        return dict(first=on[0], last=on[-1], px=on[-1] - on[0] + 1, faint_first=lo, faint_last=hi, contrast=ref)

    def dark_centroids(self, rows, cols, mid):
        """Centroids (x, y, pixels) of the two eyes: blobs of pixels much darker than the skin
        within `rows` and `cols`, round (their box at least half filled, near square), the
        largest left and right of `mid`. The outline is dark too but a thin ring: its box is
        nearly empty."""
        dark = set()
        for y in range(*rows):
            for x in range(*cols):
                r, g, b = self.px(x, y)
                if max(r, g, b) < 140 and self.diff(x, y) > 30:
                    dark.add((x, y))
        blobs, seen = [], set()
        for p in dark:
            if p in seen:
                continue
            seen.add(p)
            stack, pts = [p], []
            while stack:
                x, y = stack.pop()
                pts.append((x, y))
                for q in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                    if q in dark and q not in seen:
                        seen.add(q)
                        stack.append(q)
            xs, ys = [q[0] for q in pts], [q[1] for q in pts]
            bw, bh = max(xs) - min(xs) + 1, max(ys) - min(ys) + 1
            if len(pts) >= 20 and len(pts) >= 0.5 * bw * bh and 0.6 < bw / bh < 1.6:
                blobs.append((sum(xs) / len(pts) + 0.5, sum(ys) / len(pts) + 0.5, len(pts)))
        side = {s: max((b for b in blobs if (b[0] < mid) == (s < 0)), key=lambda b: b[2], default=None) for s in (-1, 1)}
        return side


def render(out, binary, glb, shots, ortho=True, perf=None):
    out.mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith("LIVING_GAME_")}
    env.update(LIVING_GAME_VIEW=str(Path(glb).relative_to(ROOT / "living/game/assets")), LIVING_GAME_VIEW_OUT=str(out), LIVING_GAME_VIEW_SHOTS=shots, LIVING_GAME_VIEW_CLIP="bind",
               LIVING_GAME_VIEW_PLATE="1", LIVING_GAME_SIZE=f"{SIZE[0]}x{SIZE[1]}", LIVING_GAME_HOUR="11", LIVING_GAME_DAY_MINUTES="0",
               LIVING_GAME_SETTINGS=str(out / "settings.json"), LIVING_GAME_SPRINGS="0", RUST_LOG="warn")
    if ortho:
        env.update(LIVING_GAME_VIEW_ORTHO="1", LIVING_GAME_VIEW_ORTHO_M=str(FRAME_M), LIVING_GAME_VIEW_ORTHO_Y=str(ortho_shape.MIDDLE_Y))
    if perf:
        env["LIVING_GAME_PERF"] = perf
    with (out / "client.log").open("w") as log:
        subprocess.run([binary], env=env, stdout=log, stderr=subprocess.STDOUT, timeout=600, check=True)
    return out / Path(glb).stem


def measure_ortho(folder, known):
    res, fails = {}, []
    for photo, across in (("00-front", "width_m"), ("01-side", "depth_m")):
        j = json.loads((folder / f"{photo}.ortho.json").read_text())
        k = j["px_per_m"]
        want_k = j["frame_px"][1] / FRAME_M
        if abs(k - want_k) > 1e-3 * want_k or j["pitch_deg"] != 0 or j["projection"] != "orthographic":
            fails.append(f"{photo}: the sidecar's projection {k} px/m, pitch {j['pitch_deg']}, not {want_k} level")
        pic = Picture(folder / f"{photo}.png")
        row = int(j["ground_row_px"] - known["middle_y_m"] * k)  # the equator's row
        r = pic.run(row)
        m = dict(px_per_m=k, row=row, px=r["px"], m=r["px"] / k, known_m=known[across], faint_px=r["faint_last"] - r["faint_first"] + 1)
        m["error"] = m["m"] / known[across] - 1
        if photo == "00-front":
            col = int(j["frame_px"][0] / 2)
            top = pic.run(col, horizontal=False)
            top_y = (j["ground_row_px"] - top["first"]) / k
            m["top_y_m"], m["known_top_y_m"] = top_y, known["top_y_m"]
            m["top_error_of_height"] = (top_y - known["top_y_m"]) / known["height_m"]
            eye_row = j["ground_row_px"] - known["eye_y_m"] * k
            half = known["eye_radius_m"] * k * 1.6
            c = pic.dark_centroids((int(eye_row - half), int(eye_row + half) + 1), (r["first"] + 12, r["last"] - 11), col)
            spacing = (c[1][0] - c[-1][0]) / k
            m["eye_spacing_m"], m["eye_spacing_error"] = spacing, spacing / known["eye_spacing_m"] - 1
            m["width_over_eyes"] = r["px"] / (c[1][0] - c[-1][0])
        res[photo] = m
    return res, fails


def measure_portrait(folder, known):
    res = {}
    for png in sorted(folder.glob("*.png")):
        if png.name.endswith(".plate.png"):
            continue
        pic = Picture(png)
        # The widest row of the head (above the neck's top, by the eyes' rows downward).
        best = None
        for y in range(0, pic.h, 2):
            r = pic.run(y)
            if r and (best is None or r["px"] > best[1]["px"]):
                best = (y, r)
        y, r = best
        for yy in range(max(0, y - 3), min(pic.h, y + 4)):
            rr = pic.run(yy)
            if rr and rr["px"] > r["px"]:
                y, r = yy, rr
        mid = (r["first"] + r["last"]) / 2
        c = pic.dark_centroids((0, y), (r["first"] + 12, r["last"] - 11), mid)
        spacing = c[1][0] - c[-1][0]
        ratio = r["px"] / spacing
        res[png.stem] = dict(widest_row=y, width_px=r["px"], eye_spacing_px=spacing, width_over_eyes=ratio,
                             known=known["width_over_eyes"], error=ratio / known["width_over_eyes"] - 1)
    return res


def default_binary():
    if os.environ.get("LIVING_GAME_BIN"):
        return os.environ["LIVING_GAME_BIN"]
    if os.environ.get("CARGO_TARGET_DIR"):
        return str(Path(os.environ["CARGO_TARGET_DIR"]) / "release/living-game")
    return str(ROOT / "living/target/release/living-game")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--binary", default=default_binary())
    ap.add_argument("--out", type=Path)
    ap.add_argument("--no-portrait", action="store_true", help="skip the old perspective portrait (reported only)")
    a = ap.parse_args()
    out = a.out or Path(tempfile.mkdtemp(prefix="ortho-selftest-"))
    out.mkdir(parents=True, exist_ok=True)
    # The fixture goes in the client's asset tree (git-ignored `measure/`): the view would otherwise copy
    # a file from outside it into `view/`, which a worktree may link to a shared tree.
    glb = ROOT / "living/game/assets/measure/ortho_head.glb"
    glb.parent.mkdir(parents=True, exist_ok=True)
    known = ortho_shape.write(str(glb))
    ortho_shape.write(str(out / "ortho_head.glb"))
    runs = dict(lines=None, no_outline="nooutlines", bare="nooutlines,noedges")
    result, fails = dict(binary=a.binary, out=str(out), known=known, frame_m=FRAME_M, size_px=list(SIZE)), []
    for name, perf in runs.items():
        m, f = measure_ortho(render(out / name, a.binary, glb, "front,side", perf=perf), known)
        result[name] = m
        fails += [f"{name}: {x}" for x in f]
        for photo, v in m.items():
            if name in ("lines", "bare") and abs(v["error"]) > TOL:
                fails.append(f"{name} {photo}: {v['m']:.5f} m against {v['known_m']} ({v['error']:+.2%})")
        if abs(m["00-front"]["eye_spacing_error"]) > TOL:
            fails.append(f"{name}: eye spacing {m['00-front']['eye_spacing_m']:.5f} m ({m['00-front']['eye_spacing_error']:+.2%})")
        if name == "bare" and abs(m["00-front"]["top_error_of_height"]) > TOL:
            fails.append(f"bare: the head's top at {m['00-front']['top_y_m']:.4f} m against {known['top_y_m']}")
    # What the outline and the ink add, in pixels across the head (both sides together).
    lines = {p: result["lines"][p]["px"] - result["bare"][p]["px"] for p in ("00-front", "01-side")}
    outline = {p: result["lines"][p]["px"] - result["no_outline"][p]["px"] for p in ("00-front", "01-side")}
    ink = {p: result["no_outline"][p]["px"] - result["bare"][p]["px"] for p in ("00-front", "01-side")}
    result["added_px"] = dict(outline_and_ink=lines, outline=outline, ink=ink)
    if not a.no_portrait:
        result["portrait"] = measure_portrait(render(out / "portrait", a.binary, glb, "0:8:0.36:0.88,0:0:0.36:0.88", ortho=False), known)
    result["fails"], result["accepted"] = fails, not fails
    (out / "selftest.json").write_text(json.dumps(result, indent=1))
    f, b = result["lines"]["00-front"], result["bare"]["00-front"]
    print(f"ortho {f['px_per_m']:.1f} px/m: width {b['m']:.5f} m bare ({b['error']:+.2%}), {f['m']:.5f} m with lines ({f['error']:+.2%}) "
          f"against {known['width_m']}; depth {result['bare']['01-side']['m']:.5f} m bare ({result['bare']['01-side']['error']:+.2%}); "
          f"eyes {b['eye_spacing_m']:.5f} m ({b['eye_spacing_error']:+.2%}); outline +{outline['00-front']} px, ink +{ink['00-front']} px across")
    for k, v in result.get("portrait", {}).items():
        print(f"portrait {k}: width/eyes {v['width_over_eyes']:.3f} against {v['known']:.3f} ({v['error']:+.2%})")
    print(("PASS" if not fails else "FAIL") + f": {out / 'selftest.json'}")
    for x in fails:
        print("  " + x)
    sys.exit(0 if not fails else 1)


if __name__ == "__main__":
    main()
