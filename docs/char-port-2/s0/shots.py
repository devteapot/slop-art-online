#!/usr/bin/env python3
"""S0 stills: the four bodies in the asset view, as the calibration frame shoots (11:00, soft film,
idle at 0 s, 1600 x 900), with and without the generator's shell lines.

    python3 shots.py OUT --binary BIN NAME [NAME ...]      # NAME: lookdev/own-<NAME>.glb

Shots: front portrait (0:8:0.36:0.88), three-quarter (-35:8:0.36:0.88), profile (90:8:0.36:0.88),
a closer front and three-quarter at the jaw (0:8:0.18:0.86, -35:8:0.18:0.86), Near and Middle (58°).
"""
import argparse
import os
import subprocess
from pathlib import Path

SHOTS = ['0:8:0.36:0.88', '-35:8:0.36:0.88', '90:8:0.36:0.88', '0:8:0.18:0.86', '-35:8:0.18:0.86', 'near@0', 'middle@0']


def run(glb, binary, out):
    out.mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith('LIVING_GAME_')}
    env.update(LIVING_GAME_VIEW=glb, LIVING_GAME_VIEW_SHOTS=','.join(f'idle@0/{s}' for s in SHOTS),
               LIVING_GAME_VIEW_OUT=str(out), LIVING_GAME_HOUR='11', LIVING_GAME_DAY_MINUTES='0',
               LIVING_GAME_FILM='soft', LIVING_GAME_HAIR_SHINE='crown', LIVING_GAME_SETTINGS=str(out/'settings.json'),
               LIVING_GAME_SIZE='1600x900', LIVING_GAME_VIEW_CLIP='idle', RUST_LOG='warn,living_game=info')
    with (out/'client.log').open('w') as log:
        subprocess.run([binary], env=env, stdout=log, stderr=subprocess.STDOUT, timeout=600, check=True)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('out', type=Path)
    ap.add_argument('names', nargs='+')
    ap.add_argument('--binary', required=True)
    a = ap.parse_args()
    for n in a.names:
        run(f'lookdev/own-{n}.glb', a.binary, a.out/n)
        print(n, sorted(p.name for p in (a.out/n/f'own-{n}').glob('*.png')))
