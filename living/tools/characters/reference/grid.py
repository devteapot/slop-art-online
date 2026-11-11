import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import pil
from PIL import Image, ImageDraw
out, cols, size = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]); items = [a.split('=',1) for a in sys.argv[4:]]
rows = (len(items)+cols-1)//cols
sheet = Image.new('RGB', (cols*size, rows*(size+18)), 'white'); d = ImageDraw.Draw(sheet)
for i,(label, f) in enumerate(items):
    im = Image.open(f).convert('RGBA'); bg = Image.new('RGBA', im.size, (255,255,255,255)); bg.alpha_composite(im)
    im = bg.convert('RGB'); im.thumbnail((size, size))
    x, y = (i%cols)*size, (i//cols)*(size+18)
    sheet.paste(im, (x + (size-im.width)//2, y+18)); d.text((x+4, y+3), label, fill='black')
sheet.save(out, quality=90)
