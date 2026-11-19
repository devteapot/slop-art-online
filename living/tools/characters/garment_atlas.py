"""Paint the shared cloth picture and fit the two upper garments in their bind pose."""
import argparse
from array import array
from pathlib import Path
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from merge_primitives import append_accessor, read_accessor, read_glb, write_glb


def paint(path):
    # Two padded pattern pieces, each in metres on the half-body. The same placement
    # is used on both arms. Across the back the centre line is offset away from the placket.
    row, col = np.indices((1024, 1024), dtype=float)
    x = ((col % 512 + 0.5) / 512 * 0.84) - 0.04
    z = 1.60 - (row + 0.5) / 1024
    coat = col >= 512

    def stroke(d, width):
        return np.exp(-(d / width) ** 2)

    hem = np.where(coat, 0.702, 1.075)
    wrist = np.where(coat, 0.681, 0.739)
    cuff = (x > wrist - np.where(coat, 0.072, 0.090)) & (x < wrist + 0.02)
    welt = (z < hem + np.where(coat, 0.044, 0.059)) & (x < 0.24)
    grey = 0.965 - 0.18 * cuff - 0.13 * welt
    # The raised fold casts a short shadow and catches light along its turned edge.
    for d in (x - wrist + np.where(coat, 0.072, 0.090), z - hem - np.where(coat, 0.044, 0.059)):
        grey -= 0.16 * stroke(d, 0.0028)
        grey += 0.065 * stroke(d - 0.0045, 0.0028)
    grey += (~coat) * (cuff | welt) * 0.055 * np.cos(2 * np.pi * np.where(cuff, z, x) / 0.009)
    edge = 0.058 - 0.032 * np.clip((z - 0.70) / 0.75, 0, 1)
    placket = x - edge
    grey -= coat * (0.16 * (placket < 0.027) + 0.22 * stroke(placket - 0.028, 0.003))
    grey += coat * 0.08 * stroke(placket - 0.034, 0.003)
    # Garment tension falls away from each bent elbow; hems have softer, wider folds.
    wave = z - (1.395 + 0.10 * (x - 0.46))
    grey -= 0.12 * stroke(x - 0.47, 0.065) * stroke(wave, 0.010)
    grey -= 0.08 * stroke(z - hem - 0.087 - 0.024 * np.sin(17 * x), 0.012) * stroke(x - 0.12, 0.075)
    grey += 0.014 * np.sin(2 * np.pi * x / 0.006) * np.sin(2 * np.pi * z / 0.008)
    pixels = np.uint8(np.clip(grey, 0, 1) * 255 + 0.5)
    pixels[:48, :48] = 255  # neutral swatch used by the far shells and other clothes
    Image.fromarray(pixels).convert("RGB").save(path)


def store_uv(doc, data, attrs, uv):
    # Blender already exported the cage UVs. Reuse their storage when tightly packed.
    if "TEXCOORD_0" in attrs:
        acc = doc["accessors"][attrs["TEXCOORD_0"]]
        view = doc["bufferViews"][acc["bufferView"]]
        if acc["componentType"] == 5126 and acc["type"] == "VEC2" and view.get("byteStride", 8) == 8:
            start = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
            raw = uv.astype("<f4").tobytes()
            data[start:start + len(raw)] = raw
            acc.pop("min", None)
            acc.pop("max", None)
            return
    attrs["TEXCOORD_0"] = append_accessor(doc, data, array("f", uv.ravel()), 5126, "VEC2", False, 34962)


def attach(path):
    doc, data = read_glb(path)
    cloth = {i for i, m in enumerate(doc["materials"]) if m["name"].endswith("_CLOTH")}
    if not cloth:
        return
    for mesh in doc["meshes"]:
        for prim in mesh["primitives"]:
            if prim["material"] not in cloth:
                continue
            attrs = prim["attributes"]
            pos = np.asarray(read_accessor(doc, data, attrs["POSITION"])[0]).reshape(-1, 3)
            uv = np.full((len(pos), 2), 24 / 1024)
            if mesh["name"] == "Cloth" and path.stem.startswith(("jersey", "coat-")):
                x, z, back = pos.T
                # Blend round the sides. Positive glTF Z faces the back of our VRM.
                s = np.clip((back + 0.01) / 0.09, 0, 1)
                x = abs(x) + 0.14 * s * np.clip(1 - abs(x) / 0.22, 0, 1)
                uv[:, 0] = ((x + 0.04) / 0.84 + path.stem.startswith("coat-")) / 2
                uv[:, 1] = 1.60 - z
            store_uv(doc, data, attrs, uv)
    images = doc.setdefault("images", [])
    textures = doc.setdefault("textures", [])
    samplers = doc.setdefault("samplers", [])
    samplers.append({"magFilter": 9729, "minFilter": 9987, "wrapS": 33071, "wrapT": 33071})
    images.append({"uri": "../../garment.png"})
    textures.append({"source": len(images) - 1, "sampler": len(samplers) - 1})
    for i in cloth:
        doc["materials"][i]["pbrMetallicRoughness"]["baseColorTexture"] = {"index": len(textures) - 1}
    write_glb(path, doc, data)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("paint", "attach"))
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    (paint if args.action == "paint" else attach)(args.path)
