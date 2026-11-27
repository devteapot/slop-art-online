"""Measure the morphed bind surface. Run with system Python and one or more generated GLBs."""

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "board"))
import glb


def measure(path):
    doc, buf, _ = glb.read(path)
    mesh = doc["meshes"][0]
    skin = doc["skins"][0]
    names = np.array([doc["nodes"][i]["name"] for i in skin["joints"]])
    # Inverse binds are column-major. Their inverse gives the actual pivot,
    # including the per-person shoulder, thorax and long-bone scales.
    ibm = glb.accessor(doc, buf, skin["inverseBindMatrices"]).reshape(-1, 4, 4).transpose(0, 2, 1)
    scale = doc["nodes"][-1]["scale"][0]
    pivots = dict(zip(names, np.linalg.inv(ibm)[:, :3, 3] * scale))
    parts = []
    dominant = []
    mats = []
    torso_faces = []
    for prim in mesh["primitives"]:
        attrs = prim["attributes"]
        pos = glb.accessor(doc, buf, attrs["POSITION"]).astype(float)
        for weight, target in zip(mesh["weights"], prim["targets"], strict=True):
            pos += weight * glb.accessor(doc, buf, target["POSITION"])
        joints = glb.accessor(doc, buf, attrs["JOINTS_0"])
        weights = glb.accessor(doc, buf, attrs["WEIGHTS_0"])
        dominant.extend(names[joints[np.arange(len(pos)), weights.argmax(axis=1)]])
        material = doc["materials"][prim["material"]]["name"]
        if material in ("Foundation_top_CLOTH", "Foundation_band_CLOTH"):
            ids = glb.accessor(doc, buf, prim["indices"]).reshape(-1, 3)
            torso_faces.extend(pos[ids] * scale)
        parts.extend(pos * scale)
        mats.extend([doc["materials"][prim["material"]]["name"]] * len(pos))
    points = np.asarray(parts)
    dom = np.array(dominant)
    head, hips, neck = (points[dom == "J_Bip_C_" + bone] for bone in ("Head", "Hips", "Neck"))
    x, y, _z = points.T
    h = np.ptp(y)
    hip_width = np.ptp(hips[:, 0])
    # Scan between the waistband and lower ribs. The band and top are regions
    # of the same skin. Their front-to-back orientation is -Z before scene yaw.
    torso = np.isin(mats, ["Foundation_top_CLOTH", "Foundation_band_CLOTH"])
    waistband = points[np.array(mats) == "Foundation_band_CLOTH"]
    tris = np.array(torso_faces)
    a = tris.reshape(-1, 3)
    b = np.roll(tris, 1, axis=1).reshape(-1, 3)
    rows = []
    for elevation in np.linspace(np.mean(waistband[:, 1]), waistband[:, 1].max() + 0.065 * h, 80):
        mask = (a[:, 1] < elevation) & (b[:, 1] >= elevation) | (b[:, 1] < elevation) & (a[:, 1] >= elevation)
        if not mask.any():
            continue
        start = a[mask]
        end = b[mask]
        t = (elevation - start[:, 1]) / (end[:, 1] - start[:, 1])
        row = start + (end - start) * t[:, None]
        rows.append((np.ptp(row[:, 0]), elevation, row[:, 2].min(), row[:, 2].max()))
    waist, elevation, front, back = min(rows)
    chest = points[
        torso
        & (y > elevation + 0.028 * h)
        & (y < pivots["J_Bip_L_UpperArm"][1] + 0.02 * h)
        & (abs(x) < 0.09 * h)
    ]

    def middle_z(vertices):
        return (vertices[:, 2].min() + vertices[:, 2].max()) / 2

    shoulder_span = abs(pivots["J_Bip_R_UpperArm"][0] - pivots["J_Bip_L_UpperArm"][0])
    return {
        k: round(float(v), 4)
        for k, v in {
            "height_m": h,
            "heads": h / (max(y) - head[:, 1].min()),
            "hip_pct": 100 * hip_width / h,
            "waist_pct": 100 * waist / h,
            "waist_hip": waist / hip_width,
            "shoulder_pct": 100 * shoulder_span / h,
            "shoulder_hip": shoulder_span / hip_width,
            "bust_cm": 100 * (front - chest[:, 2].min()),
            "head_forward_cm": 100 * (middle_z(hips) - middle_z(head)),
            "neck_pct": 100 * np.ptp(neck[:, 0]) / h,
            "back_cm": 100 * (chest[:, 2].max() - back),
        }.items()
    }


if __name__ == "__main__":
    print(json.dumps({Path(p).stem: measure(p) for p in sys.argv[1:]}, indent=2))
