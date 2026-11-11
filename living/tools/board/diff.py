"""What changed between two photographs of the same shot: the share of pixels that changed, and a
picture of where (the new photograph dimmed, changed pixels in red by how much)."""

import os

THRESHOLD = 28  # out of 255, on the largest channel: below this is JPEG noise and dithering


def compare(old_path, new_path, out_path):
    """Write the diff picture; return {"changed": share 0..1, "resized": bool}."""
    import numpy as np
    from PIL import Image

    new = Image.open(new_path).convert("RGB")
    old = Image.open(old_path).convert("RGB")
    resized = old.size != new.size
    if resized:
        old = old.resize(new.size, Image.BILINEAR)
    a = np.asarray(old).astype(np.int16)
    b = np.asarray(new).astype(np.int16)
    d = np.abs(a - b).max(axis=2)
    changed = d > THRESHOLD
    share = float(changed.mean())
    grey = b.mean(axis=2, keepdims=True) * 0.35 + 30
    pic = np.repeat(grey, 3, axis=2)
    k = np.clip((d - THRESHOLD) / 80.0, 0, 1)[..., None] * changed[..., None]
    red = np.array([255, 40, 30])
    pic = pic * (1 - k) + red * k
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    Image.fromarray(pic.clip(0, 255).astype(np.uint8)).save(out_path, quality=85)
    return {"changed": round(share, 4), "resized": resized}
