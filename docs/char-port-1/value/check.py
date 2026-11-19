"""Check the Middle contrast gates from the native RGB tiles stored in pixels/*.png."""
import json
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
LAYER_MIN = 2.5
GRASS_MIN = 1.5
MIN_LAYER_PIXELS = 6


def luminance(rgb):
    c = rgb / 255
    return np.where(c <= .04045, c / 12.92, ((c + .055) / 1.055) ** 2.4) @ [.2126, .7152, .0722]


def contrast(a, b):
    return (np.maximum(a, b) + .05) / (np.minimum(a, b) + .05)


def largest_component(mask):
    pixels = set(zip(*np.nonzero(mask)))
    largest = []
    while pixels:
        group = [pixels.pop()]
        for y, x in group:
            for pos in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
                if pos in pixels:
                    pixels.remove(pos)
                    group.append(pos)
        if len(group) > len(largest):
            largest = group
    if not largest:
        raise ValueError("No figure pixels identified")
    result = np.zeros_like(mask)
    result[tuple(np.array(largest).T)] = True
    return result


def measure(tile):
    image, marked, blue_ground = np.split(np.asarray(Image.open(tile).convert("RGB"), dtype=float), 3, axis=1)
    figure = largest_component(np.abs(image - blue_ground).max(axis=2) < 65)
    red, green, blue = marked.transpose(2, 0, 1)
    outer = figure & (red - green > 40) & (blue - green > 40)
    jersey = figure & (green - red > 40) & (blue - red > 40)
    light = luminance(image)
    y, x = np.nonzero(figure)
    if x.min() < 24:
        raise ValueError(f"{tile} has insufficient adjacent grass")
    grass = np.median(light[y, x.min() - 24:x.min() - 8], axis=1)
    coat_y = float(np.median(light[outer])) if outer.sum() >= MIN_LAYER_PIXELS else None
    shirt_y = float(np.median(light[jersey])) if jersey.sum() >= MIN_LAYER_PIXELS else None
    layers = float(contrast(coat_y, shirt_y)) if coat_y is not None and shirt_y is not None else None
    return dict(outer_px=int(outer.sum()), jersey_px=int(jersey.sum()), figure_px=int(figure.sum()),
                outer=coat_y, jersey=shirt_y, grass=float(np.median(grass)), layer_ratio=layers,
                figure_ratio=float(np.median(contrast(light[figure], grass))))


if __name__ == "__main__":
    results = {arm: {body: measure(HERE / "pixels" / f"{arm}-{body}.png")
                     for body in ("woman", "man", "elder", "girl")} for arm in ("main", "port")}
    print(json.dumps(results, indent=2))
    if any((m["layer_ratio"] or 0) < LAYER_MIN or m["figure_ratio"] < GRASS_MIN
           for m in results["port"].values()):
        raise SystemExit(1)
