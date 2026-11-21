import os, subprocess, sys
from pathlib import Path
SHOTS=['0:8:0.36:0.88','-35:8:0.36:0.88','180:8:0.36:0.88','0:8:0.18:0.86','near@0','near@180']
out=Path(sys.argv[1]); binary=sys.argv[2]
for n in sys.argv[3:]:
    o=out/n; o.mkdir(parents=True, exist_ok=True)
    env={k:v for k,v in os.environ.items() if not k.startswith('LIVING_GAME_')}
    env.update(LIVING_GAME_VIEW=f'view/{n}.glb', LIVING_GAME_VIEW_SHOTS=','.join(f'idle@0/{s}' for s in SHOTS), LIVING_GAME_VIEW_OUT=str(o),
               LIVING_GAME_HOUR='11', LIVING_GAME_DAY_MINUTES='0', LIVING_GAME_FILM='soft', LIVING_GAME_HAIR_SHINE='crown',
               LIVING_GAME_SETTINGS=str(o/'settings.json'), LIVING_GAME_SIZE='1600x900', LIVING_GAME_VIEW_CLIP='idle', RUST_LOG='warn,living_game=info')
    with (o/'client.log').open('w') as log:
        subprocess.run([binary], env=env, stdout=log, stderr=subprocess.STDOUT, timeout=600, check=True)
    print(n, sorted(p.name for p in (o/n).glob('*.png')))
