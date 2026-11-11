import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import G
g = G(sys.argv[1]); out = sys.argv[2]; os.makedirs(out, exist_ok=True)
for i, im in enumerate(g.j['images']):
    open(os.path.join(out, f"{i:02d}-{im.get('name','img')}.png"), 'wb').write(g.image(i))
