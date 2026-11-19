import sys
from pathlib import Path
from PIL import Image,ImageDraw
p=Path(__file__).resolve().parent
stage=sys.argv[1]
src=Image.open(p.parent/'turnaround.png').convert('RGBA')
bg=(227,226,229,255)
board=Image.new('RGB',(1120,850),bg[:3])
draw=ImageDraw.Draw(board)
for i,(name,cx,span) in enumerate([('front',177,150),('three-quarter',1142,123),('profile',410,78),('back',655,145),('near',0,0),('middle',0,0)]):
    im=Image.open(p/f'{stage}-{name}.png').convert('RGBA')
    rgb=Image.new('RGBA',im.size,bg);rgb.alpha_composite(im)
    if i<4:
        ref=Image.new('RGBA',im.size,bg);ref.paste(src.crop((cx-span,0,cx+span,810)),(160-span,0))
        for j,v in enumerate((rgb,Image.blend(ref,rgb,.5))):
            board.paste(v.resize((148,375),Image.Resampling.LANCZOS),(i*155,j*405+23))
        draw.text((i*155+5,1),name,fill='black')
        draw.text((i*155+5,407),'50% overlay',fill='black')
    else:
        box=im.getbbox()
        draw.text((635,10+(i-4)*405),name+' 58 degrees | native pixel crop',fill='black')
        board.paste(rgb.crop((550,312,1050,592)),(620,38+(i-4)*405))
        board.paste(rgb.resize((198,111)),(632,317+(i-4)*405))
board.save(p/f'{stage}-review.png')
