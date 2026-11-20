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
- **dark and brown:** with a floor on OKLab lightness (`FLOOR`), so black hair is about main's
  black at play distance and brown a step above it; up close the lock lines and the highlight
  carry them. Their shade is held at the sky's floor (`SKY`), the darkest the shade band shows: the
  sky's fill lights it, about (61, 56, 45) with a black swatch at 11:00;
- **every bin:** with a ceiling (shade 0.55, mid 0.72, light 0.79, highlight 0.86), since light
  hair's moved targets run past what the grade shows (grey's highlight 249).

**A round:** the auburn bin's swatches (the profile's own) are scaled per channel in linear light
by target / measured, as Cora's calibration was; an anchor's only in lightness (all channels by
the luminance's target / measured), its chroma the palette's own rule from Cora's swatches, so
that it carries no correction for the calibration frame's light (the second pass found grey's,
corrected channel by channel, blue on its shadow side); written to every file
(`hair_page.py --profile-only`), and drawn again. **Pass** (`check`, the GC's rule of 2026-11-20):
every band of every bin; a near-neutral band (black, grey) by its luma within 5 levels and a
neutral swatch, any other within 5 levels on every channel; white (no anchor, and its moved
targets held at grey's by the ceiling) by a neutral swatch and its luma at least 5 above grey's; a shade channel whose target lies under the sky's floor checked against the
floor (auburn's shade).
Writes OUT/bins.json (the swatches, targets, measured and deltas a round), OUT/anchors.json and
OUT/profile.json.
"""
import argparse
import json
import math
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
BINS = dict(auburn=AUBURN, dark=(19, 17, 17), brown=(51, 34, 23), light=(158, 125, 71), grey=(133, 133, 133), white=(199, 199, 194))
# Bins that are checked but have no anchor of their own: white is drawn from grey's and blond's.
# Its moved targets lie over the lightness ceiling, which holds them at grey's: so white is checked
# against grey's measured bands, not a target of its own: a neutral swatch, and its luma at least
# ORDER above grey's in every band.
CHECK_ONLY = {'white': 'grey'}
ORDER = 5
# The check (the GC, 2026-11-20). A band passes when:
# - near-neutral (its target's OKLab chroma under NEUTRAL_C: black, grey, white): its luma within
#   TOL of the target's and the swatch drawn neutral (chroma under SWATCH_C). Per channel a
#   neutral swatch shows the scene's own warm light, as main's grey does; correcting it channel by
#   channel is what turned grey's shadow side blue;
# - otherwise: every channel within TOL;
# - for the shade band, a target channel under the sky's floor (SKY: the darkest the shade band
#   shows at 11:00) is checked against the floor, which is the auburn shade's noted exception
#   (the drawing's shade lies under it in green and blue) made a rule.
TOL, NEUTRAL_C, SWATCH_C = 5, 0.03, 0.02
# Floors on OKLab lightness (the second pass, 2026-11-20): black and brown hair no lighter than
# play distance needs them to be told apart (black about main's at Middle, brown a step above it);
# up close the lock lines and the highlight carry them. S5's first floors (shade 0.35, mid 0.42,
# light 0.46, highlight 0.55, black only) lifted black toward grey at Near and Middle.
FLOOR = dict(dark=dict(shade=0.30, mid=0.31, light=0.345, highlight=0.44), brown=dict(shade=0.32, mid=0.39, light=0.43, highlight=0.47))
# Light hair's targets moved from auburn's run past what the grade shows (grey's highlight 249,
# blond's light 255): a ceiling on OKLab lightness keeps four bands and the highlight a highlight.
CEIL = dict(shade=0.55, mid=0.72, light=0.79, highlight=0.86)
# The darkest the shade band shows at 11:00 (the sky's fill on a black swatch, measured in S5):
# a floored bin's shade target is held at it, channel by channel. Auburn's drawn shade, which lies
# under it in green and blue, stays the drawing's (the exception S5 noted).
SKY = (61, 56, 45)
SHOTS = ['0:8:0.36:0.88', '-35:8:0.36:0.88']
DEBUG = dict(palette='fixed', shade=[255, 0, 0], mid=[0, 255, 0], light=[0, 0, 255], highlight=[255, 255, 0])


def lin(c):
    c = np.asarray(c, float) / 255
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def luma(c):
    return float(np.dot(np.asarray(c, float), [0.2126, 0.7152, 0.0722]))


def chroma(c):
    _, a_, b_ = palette.oklab(tuple(int(x) for x in c))
    return math.hypot(a_, b_)


def check(band, measured, target, swatch):
    """(passed, the rule used, per-channel delta, luma delta) of one band."""
    t = [max(x, y) for x, y in zip(target, SKY)] if band == 'shade' else list(target)
    d = (np.array(measured) - np.array(t)).tolist()
    dl = round(luma(measured) - luma(t), 1)
    if chroma(target) < NEUTRAL_C:
        return abs(dl) <= TOL and chroma(swatch) < SWATCH_C, 'neutral: luma and a neutral swatch', d, dl
    return max(abs(x) for x in d) <= TOL, 'per channel', d, dl


def Y(c):
    return float(np.dot(c, [0.2126, 0.7152, 0.0722]))


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
            if name in FLOOR and L < FLOOR[name][b]:
                t[b] = [palette.enc(x) for x in palette.from_oklab(FLOOR[name][b], a_, b_)]
            if name in FLOOR and b == 'shade':
                t[b] = [max(x, y) for x, y in zip(t[b], SKY)]
            if L > CEIL[b]:
                k = CEIL[b] / L  # keep the chroma's share of the lightness
                t[b] = [palette.enc(x) for x in palette.from_oklab(CEIL[b], a_ * k, b_ * k)]
        Ll, al, bl = palette.oklab(tuple(t['light']))
        Ld, ad, bd = palette.oklab(DRAWING['light'])
        if name != 'auburn' and Ll > Ld:
            # Light hair (its light band above the drawing's): the highlight a small step over
            # the bin's own light band, in its chroma, as the drawing's is over its light. Moved
            # by ratio and held under the ceiling, it came out near white, a band like a hairband
            # across the hairline.
            Lh, ah, bh = palette.oklab(DRAWING['highlight'])
            kc = math.hypot(ah, bh) / max(math.hypot(ad, bd), 1e-9)
            t['highlight'] = [palette.enc(x) for x in palette.from_oklab(min(Ll + (Lh - Ld), CEIL['highlight']), al * kc, bl * kc)]
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
    ap.add_argument('--palette-chroma', action='store_true', help="reset the anchors' chroma to the palette's own before tuning")
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
        if name == 'auburn' or name in CHECK_ONLY:
            continue
        # The seed's swatches (the last calibration's, or the page tool's); with
        # --palette-chroma, an anchor's chroma is reset to the palette's own (Cora's swatches
        # moved to the bin) at the seed's lightness, then tuned.
        rows, _ = palette.entry(palette.anchors_of(dict(hair_page.PROFILE)), tag)
        sw[name] = {b: list(rows[i]) for i, b in enumerate(BANDS)}
        if tuple(tag) in seed:
            for b in BANDS:
                if a.palette_chroma:
                    k = Y(lin(seed[tuple(tag)][b])) / max(Y(lin(sw[name][b])), 1e-6)
                    sw[name][b] = enc(lin(sw[name][b]) * k)
                else:
                    sw[name][b] = list(seed[tuple(tag)][b])
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
            anchors = [dict(ref=list(BINS[n]), **{b: sw[n][b] for b in BANDS}) for n in BINS if n != 'auburn' and n not in CHECK_ONLY]
            (a.out/'anchors.json').write_text(json.dumps(anchors, indent=1))
            (a.out/'profile.json').write_text(json.dumps(sw['auburn'], indent=1))
            subprocess.run([sys.executable, str(REPO/'living/tools/characters/hair_page.py'), str(HAIR), '--profile-only', '--anchors', str(a.out/'anchors.json'),
                            '--profile', str(a.out/'profile.json')], check=True, capture_output=True)
            set_profile(dbg)
            got = {n: measure(render(keys[n], a.out/'book-real.json', a.binary, a.out/f'r{rnd}'/n), ms[n]) for n in BINS}
            delta = {n: {b: (np.array(got[n][b]['rgb']) - np.array(tgt[n][b])).tolist() if got[n][b]['rgb'] else None for b in BANDS} for n in BINS}
            # What each bin draws: the profile's own, an anchor's, or (white) the palette's entry.
            drawn = dict(sw)
            for n in CHECK_ONLY:
                rows, _ = palette.entry(palette.anchors_of(dict(hair_page.PROFILE, **sw['auburn'], anchors=anchors)), BINS[n])
                drawn[n] = {b: list(rows[i]) for i, b in enumerate(BANDS)}
            checks = {n: {b: dict(zip(('passed', 'rule', 'delta', 'luma_delta'), check(b, got[n][b]['rgb'], tgt[n][b], drawn[n][b]))) if got[n][b]['rgb'] else dict(passed=False, rule='not measured')
                          for b in BANDS} for n in BINS if n not in CHECK_ONLY}
            for n, below in CHECK_ONLY.items():
                checks[n] = {}
                for b in BANDS:
                    m, g = got[n][b]['rgb'], got[below][b]['rgb']
                    if not (m and g):
                        checks[n][b] = dict(passed=False, rule='not measured')
                        continue
                    above = round(luma(m) - luma(g), 1)
                    checks[n][b] = dict(passed=above >= ORDER and chroma(drawn[n][b]) < SWATCH_C, rule=f'neutral swatch, luma {ORDER}+ above {below}', luma_above=above)
            ok = all(c['passed'] for n in BINS for c in checks[n].values())
            log['rounds'].append(dict(profile=sw['auburn'], anchors=anchors, measured=got, delta=delta, checks=checks, passed=ok))
            (a.out/'bins.json').write_text(json.dumps(log, indent=1))
            print(f'round {rnd}:', 'PASS' if ok else 'not yet', {n: {b: (checks[n][b].get('delta'), checks[n][b].get('luma_delta', checks[n][b].get('luma_above')), 'ok' if checks[n][b]['passed'] else 'FAIL') for b in BANDS} for n in BINS}, flush=True)
            if ok or a.measure_only or rnd == a.rounds:
                break
            for n in BINS:
                if n in CHECK_ONLY:
                    continue
                for b in BANDS:
                    m = got[n][b]['rgb']
                    if m:
                        if n == 'auburn':
                            # Cora's own swatches: channel by channel, as her calibration was.
                            ratio = lin(tgt[n][b]) / np.maximum(lin(m), 1e-4)
                        else:
                            # An anchor: its lightness, and the size of its chroma where the target
                            # has one, never its hue. Its hue stays the palette's own (moved from
                            # Cora's), so it carries no correction for the calibration frame's
                            # light: a grey corrected channel by channel came out blue wherever the
                            # light was not the frame's (the shadow side). A near-neutral target
                            # (chroma under 0.03) keeps the palette's chroma too.
                            ratio = Y(lin(tgt[n][b])) / max(Y(lin(m)), 1e-4)
                            s2 = enc(lin(sw[n][b]) * ratio)
                            Lt, at_, bt = palette.oklab(tuple(tgt[n][b]))
                            Lm, am, bm = palette.oklab(tuple(m))
                            ct, cm = math.hypot(at_, bt), math.hypot(am, bm)
                            if ct > 0.03 and cm > 0.01:
                                Ls, as_, bs = palette.oklab(tuple(s2))
                                k = min(max(ct / cm, 0.5), 2.0)
                                s2 = [palette.enc(x) for x in palette.from_oklab(Ls, as_ * k, bs * k)]
                            sw[n][b] = s2
                            continue
                        sw[n][b] = enc(lin(sw[n][b]) * ratio)
    finally:
        dbg.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
