#!/usr/bin/env python3
"""mirror_metric.py L_OUT R_OUT [JSON]: how far two mirror_pair.py runs of a mirrored pair draw as mirrors.

- **Masks:** the rope-ID frame (OUT/rope, rope_id.py: hair green, the plait magenta) gives the hair
  less the plait, which both builds share unmirrored; the irises (green eyes, from the frame with no
  hair) are taken out. Rows above the chin (image_spread's chin row), in the portrait box.
- **Axis:** the body's midline in each run's frame with no hair (the shirt's centre, rows 600-860 of
  the full frame), not the eyes (they sit 4 px off the midline at rest).
- **Measures:** each side's reach from the axis and the whole width; `mismatch`, the pixels in
  exactly one of (L mirrored about its axis onto R's) and R over the pixels in either; `edge_px`, the
  median over rows of |L mirrored's outer edge - R's| on both sides (px); and the same with the axis
  left free within ±3 px (`best_axis_*`), which separates a shift of the whole from a change of shape.
- **The acceptance** (hair-mirror, README.md): the whole hair width and image_spread's body width
  each within 2 px between the builds, and `best_axis_mismatch` at most 0.05."""
import glob, json, sys
from pathlib import Path
import numpy as np
from PIL import Image
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "s6"))
import drawing_spread as ds  # noqa: E402

BOX = (600, 160, 1000, 620)
WIDTH_PX = 2
MISMATCH = 0.05


def png(d):
    return sorted(glob.glob(str(d / "**/*.png"), recursive=True))[0]


def load(out):
    out = Path(out)
    i = np.asarray(Image.open(png(out / "rope" if (out / "rope").exists() else out / "id")).convert("RGB")).astype(int)
    f = np.asarray(Image.open(png(out / "none")).convert("RGB")).astype(int)
    hair = (i[..., 1] - i[..., 0] > 28) & (i[..., 1] - i[..., 2] > 28) & (i[..., 1] >= 60)
    r, g, b = f[..., 0], f[..., 1], f[..., 2]
    iris = (g > r + 8) & (g > b)
    iris[:BOX[1] + 100] = False
    iris[BOX[3]:] = False
    hair &= ~iris
    shirt = (abs(r - g) < 12) & (abs(g - b) < 14) & (r > 150)
    mids = [(np.nonzero(shirt[y])[0].min() + np.nonzero(shirt[y])[0].max()) / 2 for y in range(600, 860, 10) if shirt[y].any()]
    sp = json.loads((out / "spread.json").read_text())
    x0, y0, x1, y1 = BOX
    return hair[y0:y1, x0:x1], float(np.median(mids)) - x0, sp


def compare(hl, hr, cl, cr):
    ys, xs = np.nonzero(hl)
    w = hl.shape[1]
    # Whole pixels: a mirror about a half-pixel axis maps x to x' = 2c - x exactly; rounding each
    # x + 0.5 to even would fold pairs of columns together.
    xm = (int(np.floor(cr + cl + 0.5)) - xs).astype(int)
    ok = (xm >= 0) & (xm < w)
    ml = np.zeros_like(hr)
    ml[ys[ok], xm[ok]] = True
    edges = []
    for y in range(hl.shape[0]):
        a, b = np.nonzero(ml[y])[0], np.nonzero(hr[y])[0]
        if len(a) and len(b):
            edges += [abs(a.min() - b.min()), abs(a.max() - b.max())]
    return ml, float((ml ^ hr).sum() / (ml | hr).sum()), float(np.median(edges))


def main():
    hl, cl, sl = load(sys.argv[1])
    hr, cr, sr = load(sys.argv[2])
    chin = min(sl["chin_row"], sr["chin_row"])
    hl, hr = hl[:chin], hr[:chin]
    ml, mis, edge = compare(hl, hr, cl, cr)
    best = min((compare(hl, hr, cl + d, cr)[1:] + (d,) for d in np.arange(-6, 6.01, 0.5)), key=lambda t: t[0])

    def reach(m, c):
        xs = np.nonzero(m.any(axis=0))[0]
        return dict(left=round(float(c - xs.min()), 1), right=round(float(xs.max() - c), 1), width=int(xs.max() - xs.min()), area=int(m.sum()))
    res = dict(axis=dict(L=round(cl, 2), R=round(cr, 2)), chin_row=chin, L=reach(hl, cl), R=reach(hr, cr), L_mirrored=reach(ml, cr),
               mismatch=round(mis, 4), edge_px=round(edge, 2), best_axis_shift=float(best[2]), best_axis_mismatch=round(best[0], 4), best_axis_edge_px=round(best[1], 2),
               accepted=bool(abs(sl["hair_width_px"] - sr["hair_width_px"]) <= WIDTH_PX and abs(sl["body_width_px"] - sr["body_width_px"]) <= WIDTH_PX and best[0] <= MISMATCH),
               spread=dict(L={k: sl[k] for k in ("hair_width_px", "body_width_px", "body_over_eyes")}, R={k: sr[k] for k in ("hair_width_px", "body_width_px", "body_over_eyes")}))
    if len(sys.argv) > 3:
        pic = np.zeros(hr.shape + (3,), np.uint8)
        pic[ml & hr] = (200, 200, 200)
        pic[ml & ~hr] = (255, 0, 0)
        pic[hr & ~ml] = (0, 120, 255)
        Path(sys.argv[3]).write_text(json.dumps(res, indent=1))
        Image.fromarray(pic).save(Path(sys.argv[3]).with_suffix(".png"))
    print(json.dumps(res))


if __name__ == "__main__":
    main()
