#!/usr/bin/env python3
"""How a type's iris looks in each eye colour when the client recolours it.

    python3 living/tools/characters/eye_colours.py TYPES_DIR [--nominal] [--check] [--json OUT] [--sheet OUT.png [TYPE,...]]

A composed person's iris is its type's picture recoloured: the client moves the picture's
source colour to the line's eye colour (`living/game/src/toon.wesl` `recolor`, mode 3;
`characters.rs` `recolor`, `mean_color`). The source is the mean of the texels the iris's
vertices lie on, taken in linear light through a 64 x 64 summary of the picture. A coloured
picture has its hues turned to the line's (their distance from the source's hue kept at 0.4)
and its saturation and value multiplied down to the line's, or pushed up toward 1 where the
line's is above the source's.

This applies that rule to each type's iris for each eye colour a person can have
(`person_params.EYE_COLOURS`) and compares the result, in CIE76, with:

  body    the eye colour itself against the iris's body: the texels a whole file paints in
          nearly the eye colour alone (no glow, rim, pupil or lid's shade). A whole file's own
          body is not exactly its colour either; that figure is printed beside it.
  whole   the iris a whole file has in that colour (`face_paint.paint_iris`), in blocks of
          8 x 8 texels over the disc: how alike the two pictures are
  eye     the two discs' means: the eye's colour as a whole
  pupil   the lightest value at the pupil's middle, linear: above about 0.02 it reads grey

The line carries `person_params.eye_line_colour` of the eye colour, as a person's line does;
`--nominal` gives the line the eye colour itself, as lines had before the shared iris.
`--check` fails unless every type's iris has the shared iris's source colour
(`person_params.SHARED_IRIS_SOURCE`), which `eye_line_colour` is worked out from.

The rule is read from the client's source and applied here; nothing runs in the client.
"""
import glob
import io
import json
import os
import sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(HERE, "..", "blender"))
from merge_primitives import read_accessor, read_glb  # noqa: E402

HUE_SPREAD = 0.4


def linear(a):
    a = np.asarray(a, float)
    return np.where(a > 0.04045, ((a + 0.055) / 1.055) ** 2.4, a / 12.92)


def stored(a):
    a = np.clip(np.asarray(a, float), 0, 1)
    return np.where(a > 0.0031308, 1.055 * a ** (1 / 2.4) - 0.055, a * 12.92)


def hsv(a):
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    v = a.max(-1)
    c = v - a.min(-1)
    s = np.maximum(c, 1e-12)
    h = np.where(v == r, ((g - b) / s) % 6, np.where(v == g, (b - r) / s + 2, (r - g) / s + 4)) / 6
    return np.stack([np.where(c > 1e-9, h % 1, 0), np.where(v > 1e-9, c / np.maximum(v, 1e-12), 0), v], -1)


def rgb(h):
    k = (np.array([5.0, 3.0, 1.0]) + h[..., 0:1] * 6) % 6
    return h[..., 2:3] * (1 - h[..., 1:2] * np.clip(np.minimum(k, 4 - k), 0, 1))


def factor(m, t):
    return (t / m if m > 1e-4 else 1.0) if t <= m else -max((1 - t) / max(1 - m, 1e-4), 1e-4)


def remap(c, f):
    return c * f if f >= 0 else 1 - (1 - c) * (-f)


def recolor(a, mean, target):
    """The client's rule on a linear picture: its source colour `mean` moved to `target`."""
    t = hsv(np.array(target, float)[None, None, :])[0, 0]
    m = hsv(np.array(mean, float)[None, None, :])[0, 0]
    h = hsv(a)
    if m[1] < 0.12:
        h[..., 0], h[..., 1] = t[0], t[1]
    else:
        d = h[..., 0] - m[0]
        d = d - np.round(d)
        h[..., 0] = (t[0] + d * HUE_SPREAD + 1) % 1
        h[..., 1] = np.clip(remap(h[..., 1], factor(m[1], t[1])), 0, 1)
    h[..., 2] = np.clip(remap(h[..., 2], factor(m[2], t[2])), 0, 1)
    return rgb(h)


def lab(c):
    m = np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]])
    x = np.clip(c, 0, None) @ m.T / np.array([0.95047, 1.0, 1.08883])
    f = np.where(x > 0.008856, np.cbrt(x), 7.787 * x + 16 / 116)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], -1)


def iris_of(path):
    """A type file's iris: (picture in linear RGB, the mesh's UVs)."""
    j, b = read_glb(path)
    for mesh in j["meshes"]:
        for p in mesh["primitives"]:
            mat = j["materials"][p["material"]]
            if "EyeIris" not in mat.get("name", ""):
                continue
            img = j["images"][j["textures"][mat["pbrMetallicRoughness"]["baseColorTexture"]["index"]]["source"]]
            if "uri" in img:
                pic = Image.open(os.path.join(os.path.dirname(os.path.abspath(path)), img["uri"]))
            else:
                v = j["bufferViews"][img["bufferView"]]
                pic = Image.open(io.BytesIO(bytes(b[v.get("byteOffset", 0) : v.get("byteOffset", 0) + v["byteLength"]])))
            uv = np.array(read_accessor(j, b, p["attributes"]["TEXCOORD_0"])[0], float).reshape(-1, 2)
            return linear(np.asarray(pic.convert("RGB"), float) / 255), uv
    raise SystemExit(f"eye_colours: {path} has no iris")


def source_mean(pic, uv):
    """A material's source colour as the client learns it for a character's own file, which a
    type's is (`characters.rs` `mean_color`): the mean of the cells its mesh's vertices use, in
    a 64 x 64 summary of the picture (4 x 4 samples a cell, linear light). Every vertex counts
    once, whatever its triangles' area."""
    h, w = pic.shape[:2]
    ys = ((np.arange(256) + 0.5) / 256 * h).astype(int).clip(0, h - 1)
    xs = ((np.arange(256) + 0.5) / 256 * w).astype(int).clip(0, w - 1)
    cells = pic[ys][:, xs].reshape(64, 4, 64, 4, 3).mean(axis=(1, 3))
    cx = (np.mod(uv[:, 0], 1.0) * 64).astype(int).clip(0, 63)
    cy = (np.mod(uv[:, 1], 1.0) * 64).astype(int).clip(0, 63)
    return cells[cy, cx].mean(axis=0)


def whole(colour, n):
    """The iris a whole file has in this colour (sRGB 0..1), as a linear picture `n` square."""
    import face_paint

    p = face_paint.paint_iris(None, dict(iris=tuple(colour), light_side=1.0), np.random.default_rng(face_paint.SHARED_IRIS_SEED))
    p = np.round(np.clip(p, 0, 1) * 255) / 255
    if p.shape[0] != n:
        p = np.asarray(Image.fromarray((p * 255).astype(np.uint8)).resize((n, n), Image.LANCZOS), float) / 255
    return linear(p)


def blocks(a, on, k=8):
    """Means over k x k blocks, for the blocks wholly inside `on`."""
    n = a.shape[0] // k * k
    m = a[:n, :n].reshape(n // k, k, n // k, k, 3).mean(axis=(1, 3))
    return m[on[:n, :n].reshape(n // k, k, n // k, k).all(axis=(1, 3))]


def main():
    import face_paint
    import person_params

    def value(flag, n=1):
        """The words after a flag (None where they are missing or another flag)."""
        if flag not in sys.argv:
            return [None] * n
        at = sys.argv.index(flag)
        got = [a for a in sys.argv[at + 1 : at + 1 + n] if not a.startswith("--")]
        return got + [None] * (n - len(got))

    folder = sys.argv[1]
    nominal = "--nominal" in sys.argv
    eyes = {k: np.array(v, float) for k, v in person_params.EYE_COLOURS.items()}
    # The body: where a whole file's paint follows the eye colour almost alone.
    n = face_paint.IRIS_PX
    probe = [face_paint.paint_iris(None, dict(iris=c, light_side=1.0), np.random.default_rng(face_paint.SHARED_IRIS_SEED)) for c in ((0.3, 0.3, 0.3), (0.5, 0.5, 0.5))]
    body = ((probe[1] - probe[0]).mean(-1) / 0.2 > 0.9) & ((probe[1] - probe[0]).mean(-1) / 0.2 < 1.1)
    d = lambda a, b: float(np.linalg.norm(lab(a) - lab(b), axis=-1).mean())
    rows, shown, off = [], {}, []
    for f in sorted(glob.glob(os.path.join(folder, "*.glb"))):
        name = os.path.basename(f)[:-4]
        pic, uv = iris_of(f)
        mean = source_mean(pic, uv)
        if np.abs(mean - np.array(person_params.SHARED_IRIS_SOURCE)).max() > 0.002:
            off.append((name, mean))
        h, w = pic.shape[:2]
        assert h == n and w == n, f"{f}: an iris of {w} x {h}, not {n}"
        gy, gx = np.mgrid[0:h, 0:w]
        u, v = (gx + 0.5) / w, (gy + 0.5) / h
        cu, cv = 0.5 * (uv[:, 0].min() + uv[:, 0].max()), 0.5 * (uv[:, 1].min() + uv[:, 1].max())
        disc = ((u - cu) / (0.5 * np.ptp(uv[:, 0]))) ** 2 + ((v - cv) / (0.5 * np.ptp(uv[:, 1]))) ** 2 <= 1.0
        shown[name] = [pic]
        for c, s in eyes.items():
            line = s if nominal else np.array(person_params.eye_line_colour(tuple(s)))
            line = np.round(line * 255) / 255
            out = recolor(pic.copy(), mean, linear(line))
            own = whole(s, h)
            shown[name].append(out)
            rows.append(dict(
                type=name, colour=c, line="#%02x%02x%02x" % tuple(int(x) for x in np.round(line * 255)),
                body=d(out[body].mean(0)[None], linear(s)[None]), body_whole=d(own[body].mean(0)[None], linear(s)[None]),
                whole=d(blocks(out, disc), blocks(own, disc)),
                eye=d(out[disc].mean(0)[None], own[disc].mean(0)[None]),
                pupil=float(out[h // 2 - 4 : h // 2 + 4, w // 2 - 4 : w // 2 + 4].max()),
                source=[float(x) for x in mean],
            ))

    def line(label, sel):
        r = [x for x in rows if sel(x)]
        return f"  {label:10s} " + "; ".join(f"{k} median {np.median([x[k] for x in r]):.1f}, worst {max(x[k] for x in r):.1f}" for k in ("body", "whole", "eye")) + f"; pupil at most {max(x['pupil'] for x in r):.3f}"

    types = sorted(set(r["type"] for r in rows))
    print(f"eye_colours: {len(types)} types x {len(eyes)} eye colours; the line carries {'the eye colour itself' if nominal else 'eye_line_colour of it'}. CIE76: body against the eye colour, whole and eye against a whole file's iris")
    print(line("all", lambda x: True))
    for c in eyes:
        print(line(c, lambda x: x["colour"] == c) + f" (a whole file's own body: {next(x['body_whole'] for x in rows if x['colour'] == c):.1f})")
    print(f"  {len({tuple(round(x, 3) for x in r['source']) for r in rows})} different source colour(s) among the types' irises; body: {int(body.sum())} texels")
    if value("--json")[0]:
        json.dump(rows, open(value("--json")[0], "w"), indent=1)
    sheet, pick = value("--sheet", 2)
    if sheet:
        from PIL import ImageDraw

        pick = pick.split(",") if pick else types[:4]
        s, pad, left = 128, 6, 130
        im = Image.new("RGB", (left + (len(eyes) + 1) * (s + pad), 30 + (len(pick) + 1) * (s + pad)), (246, 244, 240))
        dr = ImageDraw.Draw(im)
        dr.text((left + 4, 8), "as stored", fill=(0, 0, 0))
        tile = lambda a: Image.fromarray((stored(a) * 255 + 0.5).astype(np.uint8)).resize((s, s), Image.LANCZOS)
        for k, (c, v) in enumerate(eyes.items()):
            x = left + (k + 1) * (s + pad)
            dr.rectangle([x, 4, x + 36, 24], fill=tuple(int(q) for q in np.round(v * 255)))
            dr.text((x + 42, 8), c, fill=(0, 0, 0))
        for r, name in enumerate(pick + ["a whole file"]):
            dr.text((6, 30 + r * (s + pad) + s // 2), name, fill=(0, 0, 0))
            tiles = shown[name] if name in shown else [None] + [whole(v, n) for v in eyes.values()]
            for k, t in enumerate(tiles):
                if t is not None:
                    im.paste(tile(t), (left + k * (s + pad), 30 + r * (s + pad)))
        im.save(sheet)
    if "--check" in sys.argv:
        for name, mean in off:
            print(f"eye_colours: {name}: its iris's source colour is {np.round(mean, 4).tolist()}, not the shared iris's {list(person_params.SHARED_IRIS_SOURCE)}")
        if off:
            raise SystemExit(1)
        print(f"eye_colours: every type's iris has the shared iris's source colour")


if __name__ == "__main__":
    main()
