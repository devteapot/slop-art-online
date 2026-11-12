#!/usr/bin/env python3
"""Do the generated files share one rest skeleton?

    python3 living/tools/characters/skeleton_check.py LOOKDEV_DIR [--against FILE.glb]

Every file the generator writes has the same body skeleton at rest (the `J_Bip_*` bones'
places under their parents): types, style files, whole people and the shared clip file. A
composed person is put together from several of them by bone name, and plays clips baked on
one of them, so a set whose files were built before and after a joint moved would put the
head, the hair or a collar a joint's move apart.

This reads every `.glb` under the folder's `types/`, `styles/` and `anim/` (and
`anim/own-clips.glb`, the shared clip file, when it is there), and compares each `J_Bip_*`
bone's rest translation with the first type's (or `--against`'s). It prints what differs and
exits 1 if anything does by more than a tenth of a millimetre.
"""
import glob
import json
import os
import struct
import sys


def rest(path):
    """{bone: its rest translation under its parent} for a file's `J_Bip_*` bones."""
    with open(path, "rb") as f:
        f.seek(12)
        n, _ = struct.unpack("<I4s", f.read(8))
        j = json.loads(f.read(n))
    return {x["name"]: tuple(x.get("translation", (0.0, 0.0, 0.0))) for x in j.get("nodes", []) if x.get("name", "").startswith("J_Bip_")}


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    root = args[0]
    files = sorted(glob.glob(os.path.join(root, "types", "*.glb"))) + sorted(glob.glob(os.path.join(root, "styles", "**", "*.glb"), recursive=True)) + sorted(glob.glob(os.path.join(root, "anim", "own-*.glb")))
    if not files:
        raise SystemExit(f"skeleton_check: no files under {root}")
    against = sys.argv[sys.argv.index("--against") + 1] if "--against" in sys.argv else files[0]
    want = rest(against)
    off = 0
    for f in files:
        have = rest(f)
        worst = max(((max(abs(a - b) for a, b in zip(have[k], want[k])), k) for k in have if k in want), default=(0.0, ""))
        if worst[0] > 1e-4:
            off += 1
            print(f"  {os.path.relpath(f, root)}: {worst[1]} rests {worst[0] * 1000:.1f} mm from {os.path.basename(against)}'s ({[round(x, 4) for x in have[worst[1]]]} against {[round(x, 4) for x in want[worst[1]]]})")
    clips = os.path.join(root, "anim", "own-clips.glb")
    print(f"skeleton_check: {len(files)} files against {os.path.relpath(against, root)}: {off} with a bone at another place" + ("" if os.path.exists(clips) else "; no shared clip file here (anim/own-clips.glb)"))
    if off:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
