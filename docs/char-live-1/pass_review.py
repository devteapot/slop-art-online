import sys
stage=sys.argv[1]
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

root = Path(__file__).resolve().parent
sheet = Image.open(root/"turnaround.png").convert("RGBA")
canvas = Image.new("RGB",(4*320,3*810+120),"#ededf0")
draw = ImageDraw.Draw(canvas)
font = ImageFont.load_default(size=16)
for i,(name,cx,span) in enumerate([
    ("front",177,150),("three-quarter",1142,121),
    ("profile",410,78),("back",655,145)]):
    ref = Image.new("RGBA",(320,810),sheet.getpixel((5,10)))
    ref.paste(sheet.crop((cx-span,0,cx+span,810)),(160-span,0))
    render = Image.open(root/f"{stage}-{name}.png").convert("RGBA")
    clay = Image.new("RGBA",ref.size,sheet.getpixel((5,10)))
    clay.alpha_composite(render)
    overlay = Image.blend(ref,clay,.5)
    x = i*320
    draw.text((x+20,10),name.upper(),font=font,fill="black")
    for j,(label,im) in enumerate([("Reference",ref),(stage,clay),("50% overlay",overlay)]):
        y = 35+j*837
        draw.text((x+4,y),label,font=font,fill="#383844")
        canvas.paste(im.convert("RGB"),(x,y+19))
canvas.save(root/f"{stage}-review.png")
