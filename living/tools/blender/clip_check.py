"""Measure baked clips on a character: what a look at the clip should be checked against.

Run headless on an animated character file (gen_anim.sh's or gen_person.sh's output):
    blender -b -P living/tools/blender/clip_check.py -- --in living/game/assets/lookdev/anim/own-man.glb \
        [--clips gather,work,eat] [--out own-man.check.json] [--step 2]

For each clip it plays the take on the character's own mesh and reports, in game metres:
- `lowest_m`: the lowest point any part of the mesh reaches (the floor is 0, the sole at rest),
  with the part, the time, and `below_share`, the share of the clip with something more than
  1 cm under the floor. Hands and feet through the floor show here, on this character's
  proportions and clothes, not on the raw take's skeleton.
- `hand_speed`: the hands' mean speed, and `active_share`, the share of the clip in which
  either hand moves faster than 0.25 m/s: how much of a working clip is work.
- `moved_m`: how far the head, the hands and the hips range over the clip (the largest): a clip
  that barely moves reads as frozen.
- `airborne`: stretches with both feet more than 4 cm above their resting height (hops).
- `foot_travel_m`: how far each foot's ankle travels over the floor while it is low (within
  4 cm of its resting height): sliding, for clips that should stand still.
- `finger_joints_low_m`, `foot_joints_low_m`: the lowest height the hands' joints (wrist and
  last finger joints) and the feet's (ankle, ball) reach above the floor; negative is under it.
  The skeleton's own figure, to compare with the raw take's.

It measures; it does not judge. docs/CHARACTERS.md and the check pages say what was seen.
"""

import argparse
import json
import sys

import bpy
import numpy as np

FPS = 30


def main():
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--clips", default="")
    ap.add_argument("--out")
    ap.add_argument("--step", type=int, default=2, help="sample every Nth frame")
    a = ap.parse_args(argv)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.fps = FPS  # before the import: it places keys by the scene's rate
    bpy.ops.import_scene.gltf(filepath=a.inp, bone_heuristic="BLENDER", guess_original_bind_pose=False, disable_bone_shape=True)
    arm = next(o for o in scene.objects if o.type == "ARMATURE")
    meshes = [o for o in scene.objects if o.type == "MESH"]
    want = [c for c in a.clips.split(",") if c]
    actions = {}
    for act in bpy.data.actions:
        name = act.name.split(".")[0] if act.name not in want else act.name
        if not want or act.name in want or name in want:
            actions.setdefault(act.name if act.name in want or not want else name, act)
    ad = arm.animation_data
    for tr in ad.nla_tracks:
        tr.mute = True

    def world(ob_eval):
        me = ob_eval.to_mesh()
        co = np.empty(len(me.vertices) * 3, dtype=np.float32)
        me.vertices.foreach_get("co", co)
        ob_eval.to_mesh_clear()
        m = np.array(ob_eval.matrix_world)
        return co.reshape(-1, 3) @ m[:3, :3].T + m[:3, 3]

    def bone(name):
        pb = arm.pose.bones.get(name)
        return np.array(arm.matrix_world @ pb.head) if pb else None

    # The floor is the rest pose's lowest point; a game metre is the file's unit here.
    scene.frame_set(0)
    ad.action = None
    for pb in arm.pose.bones:
        pb.matrix_basis.identity()
    dg = bpy.context.evaluated_depsgraph_get()
    dg.update()
    floor = min(float(world(o.evaluated_get(dg))[:, 2].min()) for o in meshes)
    rest_foot = {s: bone(f"J_Bip_{s}_Foot")[2] for s in "LR"}
    FINGERS = [b.name for b in arm.pose.bones if b.name.startswith(("J_Bip_L_", "J_Bip_R_")) and b.name.endswith("3")] + ["J_Bip_L_Hand", "J_Bip_R_Hand"]
    TOES = ["J_Bip_L_ToeBase", "J_Bip_R_ToeBase", "J_Bip_L_Foot", "J_Bip_R_Foot"]
    report = {}
    for name in want or sorted(actions):
        act = actions.get(name)
        if act is None:
            report[name] = dict(missing=True)
            continue
        ad.action = act
        if hasattr(ad, "action_slot") and getattr(act, "slots", None):
            ad.action_slot = act.slots[0]
        f0, f1 = (int(round(x)) for x in act.frame_range)
        frames = list(range(f0, f1 + 1, a.step))
        low, hands, feet, track, joints = [], [], [], [], []
        for f in frames:
            scene.frame_set(f)
            dg = bpy.context.evaluated_depsgraph_get()
            best = (1e9, "")
            for o in meshes:
                z = float(world(o.evaluated_get(dg))[:, 2].min())
                if z < best[0]:
                    best = (z, o.name.split(".")[0])
            low.append((best[0] - floor, best[1]))
            hands.append([bone("J_Bip_L_Hand"), bone("J_Bip_R_Hand")])
            joints.append([min(bone(n)[2] for n in FINGERS) - floor, min(bone(n)[2] for n in TOES) - floor])
            feet.append([bone("J_Bip_L_Foot"), bone("J_Bip_R_Foot")])
            track.append([bone("J_Bip_C_Head"), bone("J_Bip_C_Hips")])
        dt = a.step / FPS
        hands, feet, track = np.array(hands), np.array(feet), np.array(track)
        speed = np.linalg.norm(np.diff(hands, axis=0), axis=2) / dt  # frames-1 × 2
        z = np.array([x[0] for x in low])
        i = int(z.argmin())
        up = (feet[:, 0, 2] - rest_foot["L"] > 0.04) & (feet[:, 1, 2] - rest_foot["R"] > 0.04)
        hops, run = [], None
        for k, u in enumerate(up):
            if u and run is None:
                run = k
            if (not u or k == len(up) - 1) and run is not None:
                hops.append([round(run * dt, 2), round(k * dt, 2)])
                run = None
        travel = {}
        for si, s in enumerate("LR"):
            lowf = feet[:, si, 2] - rest_foot[s] < 0.04
            step = np.linalg.norm(np.diff(feet[:, si, :2], axis=0), axis=1)
            travel[s] = round(float(step[lowf[1:] & lowf[:-1]].sum()), 3)
        ranges = [float(np.linalg.norm(p.max(axis=0) - p.min(axis=0))) for p in (track[:, 0], track[:, 1], hands[:, 0], hands[:, 1])]
        report[name] = dict(
            seconds=round((f1 - f0) / FPS, 2), lowest_m=round(float(z[i]), 3), lowest_part=low[i][1], lowest_at_s=round(i * dt, 2), below_share=round(float((z < -0.01).mean()), 2),
            hand_speed=round(float(speed.mean()), 3), active_share=round(float((speed.max(axis=1) > 0.25).mean()), 2), moved_m=round(max(ranges), 3),
            head_moved_m=round(ranges[0], 3), airborne=hops, foot_travel_m=travel,
            finger_joints_low_m=round(float(np.array(joints)[:, 0].min()), 3), foot_joints_low_m=round(float(np.array(joints)[:, 1].min()), 3),
        )
        r = report[name]
        print(f"CHECK {name}: {r['seconds']} s, lowest {r['lowest_m'] * 100:+.1f} cm ({r['lowest_part']} at {r['lowest_at_s']} s, {r['below_share'] * 100:.0f}% under), hands {r['hand_speed']:.2f} m/s, "
              f"active {r['active_share'] * 100:.0f}%, moved {r['moved_m']:.2f} m, hops {len(hops)}, foot travel L {travel['L']:.2f} R {travel['R']:.2f} m, "
              f"finger joints {r['finger_joints_low_m'] * 100:+.1f} cm, foot joints {r['foot_joints_low_m'] * 100:+.1f} cm")
    if a.out:
        with open(a.out, "w") as f:
            json.dump(report, f, indent=1)


if __name__ == "__main__":
    main()
