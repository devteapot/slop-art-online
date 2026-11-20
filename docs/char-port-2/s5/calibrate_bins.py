#!/usr/bin/env python3
"""Calibrate the hair profile per colour bin (char-port-2 S5): the profile's own swatches at auburn
and an anchor each for the dark, light and grey bins, against targets measured in the calibration
frame, on a composed person through the client.

    python3 calibrate_bins.py OUT --binary BIN [--style bob] [--rounds 2] [--measure-only]

**The person:** a composed woman (`adult-f-b`) wearing `--style`, from a one-line book a bin, at
11:00 (soft film), idle at 0 s, the calibration portrait (0:8:0.36:0.88) and three-quarter
(-35:8:0.36:0.88).

**The bands:** a copy of the style (`zzcal-<style>.glb` beside it, removed afterwards) whose
profile is fixed and pure (shade red, mid green, light blue, highlight yellow) is drawn first;
each band is the pixels its hue rules, eroded a pixel. The bin's own render is then measured in
each band: the median colour.

**The targets** (sRGB, the screen after the grade):
- **auburn:** the drawing's hair patches, as Cora's calibration measured them (docs/char-live-3/
  final/calibration-report.json): shade (88, 42, 27), mid (152, 72, 43), light (171, 88, 56),
  highlight (187, 99, 63);
- **the other bins:** the same four moved from auburn to the bin's hair colour by the palette's own
  rule (palette.py `entry`: lightness and chroma by ratio, hue by offset, in OKLCh), the drawing's
  contrast in that colour;
- **dark:** with a floor on OKLab lightness (shade 0.35, mid 0.42, light 0.46, highlight 0.55),
  so black and near-black hair draw readable greys in order, and the lock lines (ink, near black)
  and the highlight stay visible on them. The shade band cannot go darker than its floor in any
  case: the sky's fill lights it, about (61, 56, 45) with a black swatch at 11:00;
- **every bin:** with a ceiling (shade 0.55, mid 0.72, light 0.79, highlight 0.86), since light
  hair's moved targets run past what the grade shows (grey's highlight 249).

**A round:** each bin's swatches are scaled per channel in linear light by target / measured
(the auburn bin's are the profile's own; the others are its anchors), written to every file
(`hair_page.py --profile-only`), and drawn again. Pass: every band within 8 levels of its target.
Writes OUT/bins.json (the swatches, targets, measured and deltas a round), OUT/anchors.json and
OUT/profile.json.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image

REPO = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(REPO/'living/tools/characters'), str(REPO/'living/tools')]
import look_lines  # noqa: E402
import palette  # noqa: E402
from merge_primitives import read_glb, write_glb  # noqa: E402

ASSETS = REPO/'living/game/assets'
HAIR = ASSETS/'lookdev/styles/hair'
BANDS = ('shade', 'mid', 'light', 'highlight')
AUBURN = (102, 46, 26)
DRAWING = dict(shade=(88, 42, 27), mid=(152, 72, 43), light=(171, 88, 56), highlight=(187, 99, 63))
BINS = dict(auburn=AUBURN, dark=(19, 17, 17), light=(158, 125, 71), grey=(133, 133, 133))
FLOOR = dict(shade=0.35, mid=0.42, light=0.46, highlight=0.55)
# Light hair's targets moved from auburn's run past what the grade shows (grey's highlight 249,
# blond's light 255): a ceiling on OKLab lightness keeps four bands and the highlight a highlight.
CEIL = dict(shade=0.55, mid=0.72, light=0.79, highlight=0.86)
SHOTS = ['0:8:0.36:0.88', '-35:8:0.36:0.88']
DEBUG = dict(palette='fixed', shade=[255, 0, 0], mid=[0, 255, 0], light=[0, 0, 255], highlight=[255, 255, 0])


def lin(c):
    c = np.asarray(c, float) / 255
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def enc(x):
    x = np.clip(x, 0, 1)
    return [int(v) for v in np.floor(255 * np.where(x <= 0.0031308, x * 12.92, 1.055 * x ** (1 / 2.4) - 0.055) + 0.5)]


def targets():
    out = {}
    drawn = [(AUBURN, [DRAWING[b] for b in BANDS], None)]
    for name, tag in BINS.items():
        rows, _ = palette.entry(drawn, tag)
        t = {b: list(rows[i]) for i, b in enumerate(BANDS)}
        for b in BANDS:
            L, a_, b_ = palette.oklab(tuple(t[b]))
            if name == 'dark' and L < FLOOR[b]:
                t[b] = [palette.enc(x) for x in palette.from_oklab(FLOOR[b], a_, b_)]
            if L > CEIL[b]:
                k = CEIL[b] / L  # keep the chroma's share of the lightness
                t[b] = [palette.enc(x) for x in palette.from_oklab(CEIL[b], a_ * k, b_ * k)]
        out[name] = t
    return out


def book(path, style, tags):
    lines = {}
    keys = {}
    for name, tag in tags.items():
        line = dict(type='adult-f-b', height=1.64, colors=dict(hair='#%02x%02x%02x' % tag, skin='#e8bca3', eyes='#4f7a4f'),
                    styles=dict(hair=style, outfit=['jersey-f', 'trousers-f', 'boots-f'], overlays=[]))
        k = look_lines.key_of(line)
        lines[k] = dict(person=line, words={})
        keys[name] = k
    path.write_text(json.dumps(dict(generation='c4-s5cal001', generations=[], lines=lines, decor=[])))
    return keys


def render(key, book_path, binary, out):
    out.mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith('LIVING_GAME_')}
    env.update(LIVING_GAME_VIEW=f'look:{key}', LIVING_GAME_LOOK_BOOK=str(book_path), LIVING_GAME_VIEW_SHOTS=','.join(f'idle@0/{s}' for s in SHOTS),
               LIVING_GAME_VIEW_OUT=str(out), LIVING_GAME_HOUR='11', LIVING_GAME_DAY_MINUTES='0', LIVING_GAME_FILM='soft',
               LIVING_GAME_SETTINGS=str(out/'settings.json'), LIVING_GAME_SIZE='1600x900', LIVING_GAME_VIEW_CLIP='idle', RUST_LOG='warn,living_game=info')
    with (out/'client.log').open('w') as log:
        subprocess.run([binary], env=env, stdout=log, stderr=subprocess.STDOUT, timeout=600, check=True)
    return [np.asarray(Image.open(p).convert('RGB')).astype(int) for p in sorted(out.rglob('*.png'))]


def masks(debug_imgs):
    out = []
    for a in debug_imgs:
        r, g, b = a[..., 0], a[..., 1], a[..., 2]
        mx = a.max(-1)
        sat = (mx - a.min(-1)) / np.maximum(mx, 1)
        strong = (sat > 0.6) & (mx > 40)
        m = dict(shade=strong & (r > 2 * g) & (r > 2 * b), mid=strong & (g > 2 * r) & (g > 2 * b),
                 light=strong & (b > 2 * r) & (b > 2 * g),
                 highlight=(sat > 0.3) & (mx > 60) & (r > 1.5 * b) & (g > 1.5 * b) & (np.minimum(r, g) > 0.75 * mx))  # lit pure yellow comes out pale
        for k, v in m.items():
            e = v.copy()
            for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                e &= np.roll(np.roll(v, dy, 0), dx, 1)
            m[k] = e
        out.append(m)
    return out


def measure(imgs, ms):
    res = {}
    for b in BANDS:
        px = np.concatenate([a[m[b]] for a, m in zip(imgs, ms)]) if ms else np.zeros((0, 3))
        res[b] = dict(n=int(len(px)), rgb=np.median(px, axis=0).round().astype(int).tolist() if len(px) else None)
    return res


def set_profile(fixed=None):
    """Write the debug copy's profile (fixed and pure)."""
    j, binary = read_glb(fixed)
    for m in j['materials']:
        h = m.get('extras', {}).get('slop', {}).get('hair')
        if h is not None:
            h.update(DEBUG)
            h.pop('anchors', None)
            h.pop('ref', None)
    write_glb(fixed, j, binary)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('out', type=Path)
    ap.add_argument('--binary', required=True)
    ap.add_argument('--style', default='bob')
    ap.add_argument('--rounds', type=int, default=2)
    ap.add_argument('--start', help='a bins.json to start from (its last round\'s swatches)')
    ap.add_argument('--measure-only', action='store_true')
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    tgt = targets()
    # The swatches: auburn's are the profile's own, the others its anchors.
    import hair_page
    sw = {'auburn': {b: list(hair_page.PROFILE[b]) for b in BANDS}}
    # Start from --start's last round, or the page tool's own anchors (hair_page.ANCHORS).
    seed = {tuple(x['ref']): x for x in (json.load(open(a.start))['rounds'][-1]['anchors'] if a.start else hair_page.ANCHORS)}
    if a.start:
        sw['auburn'] = json.load(open(a.start))['rounds'][-1]['profile']
    for name, tag in BINS.items():
        if name == 'auburn':
            continue
        if tuple(tag) in seed:
            sw[name] = {b: list(seed[tuple(tag)][b]) for b in BANDS}
        else:
            rows, _ = palette.entry(palette.anchors_of(dict(hair_page.PROFILE)), tag)
            sw[name] = {b: list(rows[i]) for i, b in enumerate(BANDS)}
    dbg = HAIR/f'zzcal-{a.style}.glb'
    shutil.copyfile(HAIR/f'{a.style}.glb', dbg)
    set_profile(dbg)
    log = dict(targets=tgt, rounds=[])
    try:
        bpath = a.out/'book.json'
        dkeys = book(bpath, f'zzcal-{a.style}', BINS)
        keys = book(a.out/'book-real.json', a.style, BINS)
        ms = {n: masks(render(dkeys[n], bpath, a.binary, a.out/'debug'/n)) for n in BINS}
        for rnd in range(a.rounds + 1):
            anchors = [dict(ref=list(BINS[n]), **{b: sw[n][b] for b in BANDS}) for n in BINS if n != 'auburn']
            (a.out/'anchors.json').write_text(json.dumps(anchors, indent=1))
            (a.out/'profile.json').write_text(json.dumps(sw['auburn'], indent=1))
            subprocess.run([sys.executable, str(REPO/'living/tools/characters/hair_page.py'), str(HAIR), '--profile-only', '--anchors', str(a.out/'anchors.json'),
                            '--profile', str(a.out/'profile.json')], check=True, capture_output=True)
            set_profile(dbg)
            got = {n: measure(render(keys[n], a.out/'book-real.json', a.binary, a.out/f'r{rnd}'/n), ms[n]) for n in BINS}
            delta = {n: {b: (np.array(got[n][b]['rgb']) - np.array(tgt[n][b])).tolist() if got[n][b]['rgb'] else None for b in BANDS} for n in BINS}
            ok = all(d is not None and max(abs(x) for x in d) <= 8 for n in BINS for d in delta[n].values())
            log['rounds'].append(dict(profile=sw['auburn'], anchors=anchors, measured=got, delta=delta, passed=ok))
            (a.out/'bins.json').write_text(json.dumps(log, indent=1))
            print(f'round {rnd}:', 'PASS' if ok else 'not yet', {n: {b: delta[n][b] for b in BANDS} for n in BINS}, flush=True)
            if ok or a.measure_only or rnd == a.rounds:
                break
            for n in BINS:
                for b in BANDS:
                    m = got[n][b]['rgb']
                    if m:
                        ratio = lin(tgt[n][b]) / np.maximum(lin(m), 1e-4)
                        sw[n][b] = enc(lin(sw[n][b]) * ratio)
    finally:
        dbg.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
