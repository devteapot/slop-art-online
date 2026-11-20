#!/usr/bin/env python3
"""The Middle walk clip, as char-live-2's: the embedded walk at 30 fps, five one-second cycles,
the 58° Middle camera (12 m, 44°) turning from yaw 20° by 0.1° a frame, 11:00 daylight,
1600 x 900, encoded as lossless RGB VP9 and checked frame for frame against its stills.

    python3 walk.py view/own-cora-live.glb OUT_DIR --binary BIN
"""
import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image

REPO = Path(__file__).resolve().parents[3]
FRAMES, FPS = 150, 30


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('glb')
    ap.add_argument('out')
    ap.add_argument('--binary', required=True)
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    shots = ','.join(f'walk@{(f % FPS) / FPS:.6f}/middle@{20 + .1 * f:.1f}' for f in range(FRAMES))
    env = {k: v for k, v in os.environ.items() if not k.startswith('LIVING_GAME_')}
    env.update(LIVING_GAME_VIEW=a.glb, LIVING_GAME_VIEW_SHOTS=shots, LIVING_GAME_VIEW_OUT=str(out/'stills'),
               LIVING_GAME_HOUR='11', LIVING_GAME_DAY_MINUTES='0', LIVING_GAME_FILM='soft',
               LIVING_GAME_HAIR_SHINE='crown', LIVING_GAME_SETTINGS=str(out/'settings.json'),
               LIVING_GAME_SIZE='1600x900', LIVING_GAME_VIEW_CLIP='walk',
               LIVING_GAME_SHARED_CLIPS='0',          # the file's own embedded walk
               RUST_LOG='warn,living_game=info')
    with (out/'client.log').open('w') as log:
        subprocess.run([a.binary], env=env, stdout=log, stderr=subprocess.STDOUT, timeout=900, check=True)
    stills = sorted((out/'stills'/Path(a.glb).stem).glob('[0-9]*.png'))
    assert len(stills) == FRAMES, len(stills)
    seq = out/'seq'
    seq.mkdir(exist_ok=True)
    for i, s in enumerate(stills):
        target = seq/f'{i:03d}.png'
        if target.exists():
            target.unlink()
        os.link(s, target)
    video = out/'middle-walk.webm'
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-framerate', str(FPS), '-i', str(seq/'%03d.png'), '-c:v', 'libvpx-vp9',
                    '-lossless', '1', '-pix_fmt', 'gbrp', str(video)], check=True)
    errors = {}
    for f in (0, 7, 74, 149):
        raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(video), '-vf', f'select=eq(n\\,{f})', '-vframes', '1',
                              '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'], check=True, capture_output=True).stdout
        dec = np.frombuffer(raw, np.uint8).reshape(900, 1600, 3).astype(int)
        src = np.asarray(Image.open(stills[f]).convert('RGB')).astype(int)
        errors[str(f)] = int(np.abs(dec - src).max())
    probe = json.loads(subprocess.run(['ffprobe', '-v', 'error', '-count_frames', '-show_entries',
                                       'stream=codec_name,width,height,pix_fmt,r_frame_rate,nb_read_frames:format=duration',
                                       '-of', 'json', str(video)], check=True, capture_output=True, text=True).stdout)
    check = dict(source_glb_sha256=hashlib.sha256((REPO/'living/game/assets'/a.glb).read_bytes()).hexdigest(),
                 video_sha256=hashlib.sha256(video.read_bytes()).hexdigest(), source='embedded walk', seconds=FRAMES // FPS,
                 camera='Middle, 12 m, 58-degree pitch, 44-degree FOV, yaw 20.0 to 34.9 at 0.1 degree/frame',
                 hour=11, pose_time_seconds='(frame % 30) / 30', clip_info=probe,
                 decoded_max_abs_rgb_error_vs_source=errors)
    (out/'walk-check.json').write_text(json.dumps(check, indent=2) + '\n')
    print(json.dumps(errors), video)


if __name__ == '__main__':
    main()
