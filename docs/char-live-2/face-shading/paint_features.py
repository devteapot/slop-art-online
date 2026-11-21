"""Paint Cora's procedural face maps in the generator's existing atlas layout."""
from pathlib import Path
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter


def image_array(path, mode):
    return np.asarray(Image.open(path).convert(mode), dtype=float) / 255


def write(path, values):
    Image.fromarray(np.rint(255 * np.clip(values, 0, 1)).astype('uint8')).save(path)


def grid(array):
    y, x = np.indices(array.shape[:2], dtype=float)
    return (x + 0.5) / array.shape[1], (y + 0.5) / array.shape[0]


def oval(u, v, x, y, rx, ry):
    return np.exp(-(((u - x) / rx) ** 2 + ((v - y) / ry) ** 2))


def separate_freckles(atlas, u, v):
    """Lift the generator's small isolated pigment marks into the skin tint."""
    source = Image.fromarray(np.rint(atlas * 255).astype("uint8"))
    filled = np.asarray(source.filter(ImageFilter.MaxFilter(9)), dtype=float) / 255
    residual = np.maximum(filled - atlas, 0)
    region = (np.abs(u - .5) < .28) & (v > .565) & (v < .77)
    candidates = (residual[:, :, 1] > .024) & region
    # Separate compact pigment dots from the long connected lid and mouth lines.
    mask = Image.fromarray((255 * candidates).astype("uint8"))
    coverage = np.zeros(candidates.shape, dtype=float)
    for y, x in zip(*np.nonzero(candidates)):
        if mask.getpixel((int(x), int(y))) != 255:
            continue
        ImageDraw.floodfill(mask, (int(x), int(y)), 128)
        box = (max(0,x-14), max(0,y-14), min(mask.width,x+15), min(mask.height,y+15))
        component = np.asarray(mask.crop(box)) == 128
        cy, cx = np.nonzero(component)
        if len(cx) and np.ptp(cx) <= 11 and np.ptp(cy) <= 11:
            iy, ix = cy + box[1], cx + box[0]
            atlas[iy,ix] = filled[iy,ix]
            coverage[iy,ix] = np.minimum(.60, 2.1 * residual[iy,ix,1])
        ImageDraw.floodfill(mask, (int(x), int(y)), 0)
    return Image.fromarray(np.rint(255 * coverage).astype("uint8"))


def over_skin(tint, pigment, weight):
    skin = np.indices(weight.shape)[0] > .49 * weight.shape[0]
    weight = weight * skin
    existing = tint[:, :, 3] * (1 - weight)
    alpha = weight + existing
    rgb = pigment * weight[..., None] + tint[:, :, :3] * existing[..., None]
    tint[skin, :3] = (rgb / np.maximum(alpha[..., None], 1e-8))[skin]
    tint[skin, 3] = alpha[skin]


def paint(directory, second=False, final=False):
    atlas_path = directory / 'cora.atlas.png'
    atlas = image_array(atlas_path, 'RGB')
    u, v = grid(atlas)
    freckles = separate_freckles(atlas, u, v)
    skin = v > 192 / 1024
    # The eyes occupy the first 192 rows. Below them the baked generator skin
    # carries lid detail, the mouth crease and pores. Lift the red in the skin.
    skin_scale = np.array((1.114, .963, .935))
    atlas[skin] *= skin_scale
    # One soft side of the nose and a small warm underside.
    nose = oval(u,v,.517,.731,.010,.021) + .34*oval(u,v,.501,.740,.019,.006)
    atlas *= 1 - nose[...,None] * np.array((.045,.17,.21))
    if second:
        # The seam already follows the generator mouth. Keep it fine, but
        # restore its dark centre between texels on the tapered ends.
        span = (u - .5) / .074
        crease = .7944 + .0016 * span**2
        line = np.exp(-((v-crease)/.00165)**2) * np.clip((1-abs(span))*8,0,1)
        atlas *= 1 - line[...,None]*np.array((.42,.55,.53))
        wing = oval(u,v,.513,.735,.014,.006)
        atlas *= 1 - wing[...,None]*np.array((.10,.20,.22))
    if final:
        # The lower lip projects over bare chin. The cast shade belongs to the
        # generator skin below the end of the lip-pigment guard.
        shadow_curve = .812 - .003*np.minimum(((u-.5)/.034)**2,1)
        pad = np.exp(-((u-.5)/.030)**4-((v-shadow_curve)/.0038)**2)
        atlas += .60*pad[...,None]*(np.array((.60,.32,.23))-atlas)
    write(atlas_path,atlas)

    tint_path = directory / 'cora.tint.png'
    tint = image_array(tint_path,'RGBA')
    u, v = grid(tint)
    cheek = oval(np.abs(u-.5),v,.139,.692,.089,.050)
    pigment = np.array((.965,.575,.485))
    over_skin(tint, np.array((.83,.53,.40)) if second else pigment, (.51 if second else .48) * cheek)
    # A narrow, diffuse lower lip leaves the atlas mouth crease legible.
    lip = .29 * oval(u,v,.50,.802,.060,.007)
    over_skin(tint, np.array((.91,.53,.49)), lip)
    if second:
        lip_shadow = .55*oval(u,v,.50,.812,.033,.0055)
        over_skin(tint, np.array((.58,.32,.27)), lip_shadow)
    dots = freckles.resize((tint.shape[1], tint.shape[0]), Image.Resampling.BOX)
    over_skin(tint, np.array((.64,.36,.27)), np.asarray(dots,dtype=float)/255)
    write(tint_path,tint)


def shadow(path):
    # Retain the generator's signed light directions. Spread the transition
    # out over the temples and round the jaw before it reaches the lit cheek.
    im = Image.open(path).convert('RGB').filter(ImageFilter.GaussianBlur(8))
    field = np.asarray(im,dtype=float)/255
    field[:,:,:2] = .48 + .51*field[:,:,:2]
    field[:,:,2] = 0
    write(path,field)


if __name__ == '__main__':
    if sys.argv[1] == 'shadow':
        shadow(Path(sys.argv[2]))
    else:
        paint(Path(sys.argv[1]), '--second' in sys.argv[2:], '--final' in sys.argv[2:])
