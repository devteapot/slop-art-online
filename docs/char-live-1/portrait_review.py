from pathlib import Path
from PIL import Image, ImageDraw
import sys
root=Path(__file__).resolve().parent
stage=sys.argv[1]
img=Image.open(root/'face.png').convert('RGBA')
bg=img.getpixel((5,5))
frame=Image.new('RGBA',(675,675),bg)
frame.paste(img.crop((939,0,1614,651)),(0,24))
ref=frame.resize((512,512),Image.Resampling.LANCZOS)
render=Image.new('RGBA',ref.size,bg)
render.alpha_composite(Image.open(root/f'{stage}-close.png').convert('RGBA'))
canvas=Image.new('RGB',(1536,544),bg[:3])
draw=ImageDraw.Draw(canvas)
for i,(label,panel) in enumerate([('Face sheet',ref),('Blender, 35 degrees',render),('50% overlay',Image.blend(ref,render,.5))]):
    canvas.paste(panel,(i*512,32));draw.text((i*512+12,10),label,fill='black')
canvas.save(root/f'{stage}-portrait-review.png')
