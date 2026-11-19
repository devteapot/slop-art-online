from pathlib import Path
from PIL import Image,ImageDraw
import sys
root=Path(__file__).resolve().parent
stage=sys.argv[1]
img=Image.open(root.parent/'face.png').convert('RGBA')
bg=img.getpixel((5,5))
def rendered(label):
    panel=Image.new('RGBA',(512,512),bg)
    panel.alpha_composite(Image.open(root/f'{stage}-{label}.png').convert('RGBA'))
    return panel
ref=Image.new('RGBA',(675,675),bg)
ref.paste(img.crop((939,0,1614,651)),(0,24))
ref=ref.resize((512,512),Image.Resampling.LANCZOS)
def row(name,panels,size):
    board=Image.new('RGB',(len(panels)*size,size+30),bg[:3]);draw=ImageDraw.Draw(board)
    for i,(label,p) in enumerate(panels):
        board.paste(p.resize((size,size),Image.Resampling.LANCZOS),(size*i,30));draw.text((size*i+8,9),label,fill='black')
    board.save(root/f'{stage}-{name}.png')
im=rendered('close')
row('portrait-review',[('Face sheet',ref),('Blender 35 degrees',im),('50% overlay',Image.blend(ref,im,.5))],430)
row('expression-review',[(name,rendered(name)) for name in ('neutral','blink','talk','smile','returned')],270)
