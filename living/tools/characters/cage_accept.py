#!/usr/bin/env python3
"""Accept the cage heads against what they were built to: each face type's head, measured with
the reference's own measuring tool, beside the type's numbers.

    python3 living/tools/characters/cage_accept.py REF_DIR [TYPE ...] [--tolerance 0.03] [--keep DIR]

For each type (default: all) this builds the head's skin from the cage (cage_head.CageFace, the
whole skull: nothing cut away under the hair), writes it as a small GLB with the face-skin
material's name, runs `living/tools/characters/reference/measure.py` on it (REF_DIR is that
tool's output folder, .local/ref) and compares with the type's record:

- the face's full width within 0.15 H and 0.30 H of depth behind the bridge, at eight heights
  from the chin to 0.76 H (docs/CHARACTER_REFERENCE.md §6.1: the acceptance for the cage);
- the eye's height, spacing, width and height; how far it sits behind the brow and the cheek;
  the nose tip's height and how far it stands out.

`adult-f-b` is the reference's own proportions, so its row is the reference's. A type passes when
every width is within the tolerance (0.03 H) and the eye's centre and spacing within 0.02 H.
Exit status 1 if any type fails. numpy; no Blender.
"""

import argparse
import json
import os
import struct
import subprocess
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "blender"))
import cage_head  # noqa: E402
import face_types  # noqa: E402
import person_params  # noqa: E402


def write_skin_glb(path, v, faces, chin=1.535):
    """A head's skin as a GLB the measuring tool reads: Y up, facing -Z, the chin at 1.535 m."""
    tris = []
    for f in faces:
        tris += [f[0], f[1], f[2]] + ([f[0], f[2], f[3]] if len(f) == 4 else [])
    used = sorted(set(tris))
    index = {i: k for k, i in enumerate(used)}
    p = np.array([(v[i][0], v[i][2], -v[i][1]) for i in used], dtype=np.float32)
    p[:, 1] += chin - p[:, 1].min()
    idx = np.array([index[i] for i in tris], dtype=np.uint32)
    nrm = np.tile(np.array([0.0, 0.0, -1.0], dtype=np.float32), (len(p), 1))  # the tool reads normals and UVs but measures positions
    uv = np.zeros((len(p), 2), dtype=np.float32)
    parts = [p.tobytes(), nrm.tobytes(), uv.tobytes(), idx.tobytes()]
    offsets = [sum(len(x) for x in parts[:k]) for k in range(4)]
    blob = b"".join(parts)
    j = dict(asset=dict(version="2.0"), scene=0, scenes=[dict(nodes=[0])], nodes=[dict(mesh=0, name="Face")],
             meshes=[dict(name="Face", primitives=[dict(attributes=dict(POSITION=0, NORMAL=1, TEXCOORD_0=2), indices=3, material=0)])], materials=[dict(name="M00_000_00_Face_00_SKIN")],
             buffers=[dict(byteLength=len(blob))], bufferViews=[dict(buffer=0, byteOffset=offsets[k], byteLength=len(parts[k]), target=34962 if k < 3 else 34963) for k in range(4)],
             accessors=[dict(bufferView=0, componentType=5126, count=len(p), type="VEC3", min=p.min(axis=0).tolist(), max=p.max(axis=0).tolist()), dict(bufferView=1, componentType=5126, count=len(p), type="VEC3"),
                        dict(bufferView=2, componentType=5126, count=len(p), type="VEC2"), dict(bufferView=3, componentType=5125, count=len(idx), type="SCALAR")])
    js = json.dumps(j, separators=(",", ":")).encode()
    js += b" " * (-len(js) % 4)
    blob += b"\0" * (-len(blob) % 4)
    with open(path, "wb") as f:
        f.write(struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(js) + 8 + len(blob)))
        f.write(struct.pack("<II", len(js), 0x4E4F534A) + js)
        f.write(struct.pack("<II", len(blob), 0x004E4942) + blob)


def measure_type(t, ref, keep=None):
    """A type's cage head through the measuring tool: (the measured landmark set, triangles in the skin)."""
    look = person_params.resolve(person_params.draw(dict(seed=1, sex="female", age=30)))["look"]
    hf = cage_head.CageHead(face_types.apply(t, {}))
    face = cage_head.CageFace(hf, look)
    m = face.mesh
    skin = [f for f, k in zip(m.f, m.fm) if k == "face"][: len(face.skin_faces) + 2 * sum(len(r["ring"]) for r in face.rings.values())]  # the skin and the lids' rims, not the ears
    name = t["id"]
    glb = os.path.join(keep or os.path.join(ref, "npz"), f"cage_{name}.glb")
    write_skin_glb(glb, np.array(m.v), skin)
    out = os.path.join(ref, "npz", f"cage_{name}_m.json")
    top = 1.535 + cage_head.H_FILE * t["skull"]["crown"]
    subprocess.run([sys.executable, "-I", os.path.join(HERE, "reference", "measure.py"), os.path.abspath(glb), os.path.join("npz", os.path.basename(out)), str(top)], cwd=ref, check=True, capture_output=True)
    return face_types.measure_one(out), sum(1 if len(f) == 3 else 2 for f in skin)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("ref")
    ap.add_argument("types", nargs="*")
    ap.add_argument("--tolerance", type=float, default=0.03)
    ap.add_argument("--keep", help="a folder for the heads' GLBs (default: REF_DIR/npz)")
    ap.add_argument("--table", action="store_true", help="print every width, not only the summary")
    ap.add_argument("--json")
    a = ap.parse_args()
    data = face_types.load()
    ids = a.types or list(data["types"])
    failed, rows = [], {}
    for tid in ids:
        t = data["types"][tid]
        m, tris = measure_type(t, os.path.abspath(a.ref), a.keep)
        s, e, no = t["sections"], t["eye"], t["nose"]
        widths = []
        for i, z in enumerate(face_types.Z):
            if z > 0.76:
                continue
            for k in ("w15", "w30"):
                if m[k][i] is not None and s[k][i] is not None:
                    widths.append((abs(m[k][i] - s[k][i]), z, k, m[k][i], s[k][i]))
        worst = max(widths)
        eye = dict(z=m["eye_z"] - e["z"], apart=m["eye_apart"] - e["apart"], w=m["eye_w"] - e["w"], h=m["eye_h"] - e["h"], brow=m["socket_brow"] - e["behind_brow"], cheek=m["socket_cheek"] - e["behind_cheek"])
        ok = worst[0] <= a.tolerance and abs(eye["z"]) <= 0.02 and abs(eye["apart"]) <= 0.02
        if not ok:
            failed.append(tid)
        rows[tid] = dict(ok=ok, triangles=tris, worst_width=round(worst[0], 3), worst_at=[worst[1], worst[2]], widths=[[z, k, round(x, 3), y] for _, z, k, x, y in widths], eye={k: round(v, 3) for k, v in eye.items()},
                         nose_tip_z=round(m["nose_tip_z"] - no["tip_z"], 3), nose_out=round(m["nose_out"] - no["out"], 3), measured=m)
        print(f"{tid:12s} {'ok  ' if ok else 'FAIL'} {tris} triangles; widths within {worst[0]:.3f} H (worst: {worst[2]} at {worst[1]:.2f} H, {worst[3]:.3f} for {worst[4]:.3f}); "
              f"eye centre {eye['z']:+.3f}, apart {eye['apart']:+.3f}, width {eye['w']:+.3f}, height {eye['h']:+.3f}; behind brow {eye['brow']:+.3f}, cheek {eye['cheek']:+.3f}; nose tip {rows[tid]['nose_tip_z']:+.3f}, out {rows[tid]['nose_out']:+.3f}")
        if a.table:
            for z in face_types.Z:
                cells = [f"{k} {x:.3f}/{y:.3f}" for zz, k, x, y in rows[tid]["widths"] if zz == z]
                if cells:
                    print(f"    {z:.2f} H: " + "   ".join(cells))
    if a.json:
        json.dump(rows, open(a.json, "w"), indent=1)
    print(f"{len(ids) - len(failed)} of {len(ids)} types within {a.tolerance} H" + (f"; failed: {', '.join(failed)}" if failed else ""))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
