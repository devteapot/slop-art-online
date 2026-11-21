#!/usr/bin/env python3
"""Composed people from a look book, drawn by the client with their type files' ink and without
(`LIVING_GAME_COMPOSED_SLOP=noink`), to see the type files' carriers on the composed path.

    python3 composed_shots.py BOOK.json OUT --binary BIN [KEY ...]     # default: every line

Shots as shots.py's (11:00, soft film, idle at 0 s, 1600 x 900): a front and a three-quarter
close-up, Near and Middle.
"""
import argparse
import json
import os
import subprocess
from pathlib import Path

SHOTS = ['0:8:0.18:0.86', '-35:8:0.18:0.86', 'near@0', 'middle@0']


def run(key, book, binary, out, slop):
    out.mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith('LIVING_GAME_')}
    env.update(LIVING_GAME_VIEW=f'look:{key}', LIVING_GAME_LOOK_BOOK=str(book), LIVING_GAME_COMPOSED_SLOP=slop,
               LIVING_GAME_VIEW_SHOTS=','.join(f'idle@0/{s}' for s in SHOTS), LIVING_GAME_VIEW_OUT=str(out),
               LIVING_GAME_HOUR='11', LIVING_GAME_DAY_MINUTES='0', LIVING_GAME_FILM='soft', LIVING_GAME_HAIR_SHINE='crown',
               LIVING_GAME_SETTINGS=str(out/'settings.json'), LIVING_GAME_SIZE='1600x900', LIVING_GAME_VIEW_CLIP='idle', RUST_LOG='warn,living_game=info')
    with (out/'client.log').open('w') as log:
        subprocess.run([binary], env=env, stdout=log, stderr=subprocess.STDOUT, timeout=600, check=True)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('book', type=Path)
    ap.add_argument('out', type=Path)
    ap.add_argument('keys', nargs='*')
    ap.add_argument('--binary', required=True)
    a = ap.parse_args()
    keys = a.keys or sorted(json.loads(a.book.read_text())['lines'])
    for k in keys:
        for slop in ('on', 'noink'):
            run(k, a.book.resolve(), a.binary, a.out/k/slop, slop)
            print(k, slop, sorted(str(p.relative_to(a.out)) for p in (a.out/k/slop).rglob('*.png')))
