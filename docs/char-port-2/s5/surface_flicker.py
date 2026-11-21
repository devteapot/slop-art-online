#!/usr/bin/env python3
"""How much the hair's own surface flickers in the game camera's pans and zooms (the second pass:
B2 lays main's strands under the bands, a texture read without mips from the page PNG, so it may
sparkle where B1's smooth bands do not).

    python3 surface_flicker.py render OUT --binary BIN --tag NAME [--style bob]
    python3 surface_flicker.py score OUT TABLE.json [--tags b1,b2,main]

**Renders** (three runs: auburn, white, and auburn again, whose differences from the first are
the clock's blink and are left out;the hair_shimmer camera: Near, Middle and Far, a pan of 16 stills 0.1° a frame and a
zoom of 16, 0.3% a frame; 1600x900, 11:00, soft film, idle at 0 s, springs off) of a composed
woman in the style, twice: auburn and white hair.

**The score**, per sequence: the hair is where the two colours differ by more than 40 levels in
every frame. F = sum over frames i and hair pixels of |L(i+1) - 2 L(i) + L(i-1)| over the sum of
L(i): the second temporal difference, which a smooth camera path keeps near 0 for a surface that
moves smoothly and which grows when texture comes and goes (as ink_shimmer.py's metric, without
the ink). Compared between tags: the same people, the same frames.
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image

REPO = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(REPO/'living/tools/characters')]
import ink_shimmer  # noqa: E402
import look_lines  # noqa: E402
import palette  # noqa: E402

COLOURS = ('auburn', 'white')
RUNS = (('auburn', 'auburn'), ('white', 'white'), ('again', 'auburn'))  # (folder, colour): auburn twice, for the blink


def render(out, binary, tag, style):
    lines, keys = {}, {}
    for c in COLOURS:
        line = dict(type='adult-f-b', height=1.64, colors=dict(hair=palette.HAIR_COLOURS[c], skin='#e8bca3', eyes='#4f7a4f'),
                    styles=dict(hair=style, outfit=['jersey-f', 'trousers-f', 'boots-f'], overlays=[]))
        keys[c] = look_lines.key_of(line)
        lines[keys[c]] = dict(person=line, words={})
    d = out/tag
    d.mkdir(parents=True, exist_ok=True)
    (d/'book.json').write_text(json.dumps(dict(generation='c4-s5flick1', generations=[], lines=lines, decor=[])))
    for name, c in RUNS:
        o = d/name
        o.mkdir(parents=True, exist_ok=True)
        env = {k: v for k, v in os.environ.items() if not k.startswith('LIVING_GAME_')}
        env.update(LIVING_GAME_VIEW=f'look:{keys[c]}', LIVING_GAME_LOOK_BOOK=str(d/'book.json'), LIVING_GAME_VIEW_SHOTS=ink_shimmer.shots('idle'),
                   LIVING_GAME_VIEW_OUT=str(o), LIVING_GAME_HOUR='11', LIVING_GAME_DAY_MINUTES='0', LIVING_GAME_FILM='soft', LIVING_GAME_SETTINGS=str(o/'settings.json'),
                   LIVING_GAME_SIZE='1600x900', LIVING_GAME_SPRINGS='0', LIVING_GAME_VIEW_CLIP='idle', RUST_LOG='warn')
        with (o/'client.log').open('w') as log:
            subprocess.run([binary], env=env, stdout=log, stderr=subprocess.STDOUT, timeout=900, check=True)
        print(tag, name, flush=True)


def score(out, path, tags):
    L = lambda f: (lambda a: a[..., 0] * 0.2126 + a[..., 1] * 0.7152 + a[..., 2] * 0.0722)(np.asarray(Image.open(f).convert('RGB')).astype(float))
    res = {}
    for tag in tags:
        fr = {name: ink_shimmer.stills(str(out/tag/name)) for name, _ in RUNS}
        res[tag] = {}
        for si, (stop, _) in enumerate(ink_shimmer.sequences(())):
            for mi, move in enumerate(('pan', 'zoom')):
                s = (2 * si + mi) * ink_shimmer.FRAMES
                A = np.array([L(f) for f in fr['auburn'][s:s + ink_shimmer.FRAMES]])
                W = np.array([L(f) for f in fr['white'][s:s + ink_shimmer.FRAMES]])
                G = np.array([L(f) for f in fr['again'][s:s + ink_shimmer.FRAMES]])
                # The hair: the two colours apart in every frame; not where the two auburn runs
                # differ in any frame (the client's blink runs on the clock), dilated 3 px.
                blink = (np.abs(G - A) > 8).any(0)
                for _ in range(3):
                    blink = blink | np.roll(blink, 1, 0) | np.roll(blink, -1, 0) | np.roll(blink, 1, 1) | np.roll(blink, -1, 1)
                m = (np.abs(W - A) > 40).all(0) & ~blink
                d2 = np.abs(A[2:] - 2 * A[1:-1] + A[:-2])[:, m].sum()
                res[tag][f'{stop} {move}'] = dict(pixels=int(m.sum()), F=round(float(d2 / max(A[1:-1][:, m].sum(), 1e-9)), 4))
        print(tag, {k: v['F'] for k, v in res[tag].items()})
    Path(path).write_text(json.dumps(res, indent=1))


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd')
    ap.add_argument('out', type=Path)
    ap.add_argument('dest', nargs='?')
    ap.add_argument('--binary')
    ap.add_argument('--tag')
    ap.add_argument('--tags', default='b1,b2,main')
    ap.add_argument('--style', default='bob')
    a = ap.parse_args()
    if a.cmd == 'render':
        render(a.out, a.binary, a.tag, a.style)
    else:
        score(a.out, a.dest, a.tags.split(','))
