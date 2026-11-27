"""Compose the game's orthographic photographs at their recorded pixel scale."""

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont


def lineup(directory, output):
    width = 375
    names = ("base", "woman", "man", "elder", "child")
    sheet = Image.new("RGB", (10 * width, 1970), "#e6e7e5")
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.truetype("/usr/share/fonts/urw-base35/NimbusSans-Regular.otf", 32)
    draw.text(
        (15, 10),
        "Foundation   /   Front and right profile   /   459 px per metre",
        font=font,
        fill="#233037",
    )
    for i, name in enumerate(names):
        draw.text(
            (i * 2 * width + 16, 65), name.capitalize(), font=font, fill="#233037"
        )
        folder = directory / ("own-" + name)
        for j, path in enumerate(sorted(folder.glob("*.ortho.json"))):
            meta = json.loads(path.read_text())
            assert abs(meta["px_per_m"] - 900 / 1.96) < 0.01 and meta["pitch_deg"] == 0
            assert meta["yaw_deg"] == (0, 90)[j]
            photo = folder / meta["photo"]
            a = np.asarray(Image.open(photo).convert("RGB"), int)
            plate = np.asarray(
                Image.open(photo.with_suffix(".plate.png")).convert("RGB"), int
            )
            binary = Image.fromarray((np.abs(a - plate).max(2) > 3).astype("uint8"))
            binary = binary.filter(ImageFilter.MaxFilter(5)).filter(
                ImageFilter.MinFilter(5)
            )
            mask = np.asarray(binary) > 0
            mask[round(meta["ground_row_px"]) + 2 :] = False
            crop = np.s_[:, 800 - width // 2 : 800 + width // 2]
            m = mask[crop]
            for row in range(2):
                colors = np.where(
                    m[..., None], a[crop] if row else [35, 48, 55], [230, 231, 229]
                ).astype("uint8")
                sheet.paste(
                    Image.fromarray(colors), ((i * 2 + j) * width, 115 + row * 920)
                )
    sheet.save(output)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("directory", type=Path)
    p.add_argument("output", type=Path)
    a = p.parse_args()
    lineup(a.directory, a.output)
