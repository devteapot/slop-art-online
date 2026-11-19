import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import pil
from PIL import Image, ImageDraw
out = sys.argv[1]; h = int(sys.argv[2]); files = sys.argv[3:]
ims = []
for f in files:
    im = Image.open(f).convert('RGBA'); bg = Image.new('RGBA', im.size, (128,128,128,255)); bg.alpha_composite(im)
    im = bg.convert('RGB'); im = im.resize((max(1,int(im.width*h/im.height)), h)); ims.append((os.path.basename(f), im))
W = sum(i.width for _,i in ims) + 6*len(ims)
sheet = Image.new('RGB', (W, h+16), 'white'); x = 0; d = ImageDraw.Draw(sheet)
for n, im in ims:
    sheet.paste(im, (x, 16)); d.text((x+2, 2), n[:40], fill='black'); x += im.width + 6
sheet.save(out, quality=88)
