"""Rasterize Cora's broad highlight strokes in the authored lock UV islands."""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image


def paint(layout_file, output):
    layout = json.loads(Path(layout_file).read_text())
    size = layout["size"]
    rgb = np.zeros((size, size, 3), dtype=np.uint8)
    rgb[:, :, 1] = 255
    for island in layout["islands"]:
        if not island["highlight"]:
            continue
        left, top, right, bottom = island["box"]
        x = ((np.arange(left, right) + 0.5 - left) / (right - left))[None, :]
        y = ((np.arange(top, bottom) + 0.5 - top) / (bottom - top))[:, None]
        angle = (x - 0.5) * 2 * np.pi
        across, outward = np.sin(angle), np.cos(angle)
        seed = island["seed"]
        if island["kind"] == "sweep":
            along = 0.29 + 0.025 * np.sin(seed) + 0.052 * across
            stroke = np.clip((0.085 - abs(y - along)) / 0.036, 0, 1)
            facing = np.clip((outward - 0.18) / 0.43, 0, 1)
        else:
            along = 0.36 + 0.025 * np.sin(seed) + 0.05 * across
            stroke = np.clip((0.105 - abs(y - along)) / 0.035, 0, 1)
            facing = np.clip((outward - 0.20) / 0.38, 0, 1)
        rgb[top:bottom, left:right, 0] = (255 * stroke * facing).round().astype(np.uint8)
    Image.fromarray(rgb).save(output)


if __name__ == "__main__":
    paint(*sys.argv[1:])
