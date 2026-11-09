#!/usr/bin/env python3
"""Merge a GLB's primitives that share a material inside each mesh, to cut draw calls.

    python3 living/tools/merge_primitives.py IN.glb OUT.glb

VRoid exports hair as dozens of primitives with the same two or three materials (Vivi: 78 in one
mesh), and every primitive is its own draw call in each pass: the main pass, the prepass and
every shadow cascade. Primitives of one mesh share its skin, so those with the same material,
attribute set and mode, and no morph targets, are concatenated into one: vertex attributes are
appended and indices offset. Nodes, skins, animations, materials and morphing primitives are left
as they are, so animation clips grafted by node name still apply. The old accessors stay in the
buffer unused (a little extra size); new data is appended. Plain Python, no dependencies.
"""

import json
import struct
import sys
from array import array

COMPONENT = {5120: "b", 5121: "B", 5122: "h", 5123: "H", 5125: "I", 5126: "f"}
SIZE = {5120: 1, 5121: 1, 5122: 2, 5123: 2, 5125: 4, 5126: 4}
COUNT = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


def read_glb(path):
    data = open(path, "rb").read()
    assert data[:4] == b"glTF", "not a GLB"
    jlen = struct.unpack_from("<I", data, 12)[0]
    j = json.loads(data[20 : 20 + jlen])
    off = 20 + jlen
    blen = struct.unpack_from("<I", data, off)[0]
    return j, bytearray(data[off + 8 : off + 8 + blen])


def write_glb(path, j, binary):
    while len(binary) % 4:
        binary.append(0)
    j["buffers"][0]["byteLength"] = len(binary)
    js = json.dumps(j, separators=(",", ":")).encode()
    js += b" " * ((4 - len(js) % 4) % 4)
    total = 12 + 8 + len(js) + 8 + len(binary)
    with open(path, "wb") as f:
        f.write(struct.pack("<III", 0x46546C67, 2, total))
        f.write(struct.pack("<II", len(js), 0x4E4F534A) + js)
        f.write(struct.pack("<II", len(binary), 0x004E4942) + bytes(binary))


def read_accessor(j, binary, i):
    """Values of an accessor as a flat array, and its (componentType, type, normalized)."""
    a = j["accessors"][i]
    ct, n = a["componentType"], COUNT[a["type"]]
    bv = j["bufferViews"][a["bufferView"]]
    base = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
    elem = SIZE[ct] * n
    stride = bv.get("byteStride") or elem
    out = array(COMPONENT[ct])
    for k in range(a["count"]):
        o = base + k * stride
        out.frombytes(bytes(binary[o : o + elem]))
    return out, (ct, a["type"], a.get("normalized", False))


def append_accessor(j, binary, values, ct, typ, normalized, target=None):
    while len(binary) % 4:
        binary.append(0)
    raw = values.tobytes()
    view = {"buffer": 0, "byteOffset": len(binary), "byteLength": len(raw)}
    if target:
        view["target"] = target
    binary.extend(raw)
    j["bufferViews"].append(view)
    n = COUNT[typ]
    acc = {"bufferView": len(j["bufferViews"]) - 1, "componentType": ct, "count": len(values) // n, "type": typ}
    if normalized:
        acc["normalized"] = True
    if typ in ("VEC3",) and ct == 5126:
        xs, ys, zs = values[0::3], values[1::3], values[2::3]
        acc["min"] = [min(xs), min(ys), min(zs)]
        acc["max"] = [max(xs), max(ys), max(zs)]
    j["accessors"].append(acc)
    return len(j["accessors"]) - 1


def merge(j, binary):
    before = after = 0
    for mesh in j.get("meshes", []):
        prims = mesh["primitives"]
        before += len(prims)
        groups, keep = {}, []
        for p in prims:
            if p.get("targets") or "indices" not in p:
                keep.append(p)
                continue
            key = (p.get("material"), p.get("mode", 4), tuple(sorted(p["attributes"])))
            groups.setdefault(key, []).append(p)
        merged = []
        for (material, mode, names), group in groups.items():
            if len(group) == 1:
                merged.append(group[0])
                continue
            attrs, fmt = {}, {}
            indices = array("I")
            offset = 0
            for p in group:
                count = j["accessors"][p["attributes"]["POSITION"]]["count"]
                for name in names:
                    vals, f = read_accessor(j, binary, p["attributes"][name])
                    if name not in attrs:
                        attrs[name], fmt[name] = vals, f
                    else:
                        assert fmt[name] == f, f"{name} formats differ in one material group"
                        attrs[name].extend(vals)
                idx, _ = read_accessor(j, binary, p["indices"])
                indices.extend(v + offset for v in idx)
                offset += count
            new = {"attributes": {}, "material": material, "mode": mode}
            if material is None:
                del new["material"]
            for name in names:
                ct, typ, norm = fmt[name]
                new["attributes"][name] = append_accessor(j, binary, attrs[name], ct, typ, norm, 34962)
            ict = 5125 if offset > 65535 else 5123
            if ict == 5123:
                indices = array("H", indices)
            new["indices"] = append_accessor(j, binary, indices, ict, "SCALAR", False, 34963)
            merged.append(new)
        mesh["primitives"] = keep + merged
        after += len(mesh["primitives"])
    return before, after


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    j, binary = read_glb(sys.argv[1])
    before, after = merge(j, binary)
    write_glb(sys.argv[2], j, binary)
    print(f"MERGED {sys.argv[1]} -> {sys.argv[2]}: {before} primitives -> {after}")


if __name__ == "__main__":
    main()
