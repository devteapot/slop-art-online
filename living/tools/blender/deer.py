"""A stylised deer with a procedural quadruped rig and keyed clips, for the game client.

    blender -b -P living/tools/blender/deer.py -- --out living/game/assets/lookdev/anim/deer.glb
        [--summary deer.clips.json]

The rig, keying, markers and export are `quadruped.py`'s, shared with the wolf, with the same
bones, so the client draws both alike (`bodies.rs`, `anim.rs`, `gait.rs`). The deer is about
1.0 m at the shoulder and 1.6 m from nose to rump, with long thin legs on rigid cannons, a long
neck that reaches the grass, big ears and a short tail with a white underside it flags when
alarmed. It is vertex-coloured on a white `Body` material (the client wears it with the shared
vertex-colour toon, so a herd adds no material), faces +Z in glTF and stands with its origin on
the ground.

Clips (natural speed in m/s where it moves):
- idle (loop, 10 s): grazes, head down cropping, then lifts its head to chew and look round, and
  lowers it again. A deer at rest in the open spends most of its time like this.
- graze (loop, 4 s): head down cropping the whole time (for when the rules say it grazes).
- walk (loop, 1.3), trot (loop, 3.7: the rules' deer `move_speed`), run (loop, a bound, 4.6:
  the rules' flee is 1.15 × the move speed, 4.26 m/s). The sidecar's `band` (1.04) narrows the
  blend between gaits, so the rules' trot and flee each play one gait.
- startle (0.6 s): head snaps up, the tail flags, the hind end gathers and springs into flight.
- hit (a flinch, 0.45 s, the client's HIT_MS) and death (1.6 s, ends lying on its side).

The summary gives each clip's paw contact windows (`contacts`), and each gait's `sync: "hl"`
(the left hind paw comes down at phase 0) and its legs' worst `stretch_m` (how far a leg is asked
to reach past its length).
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bmesh  # noqa: E402
from quadruped import LEGS, P, Part, Skeleton, args, build, bump, joint, lerp, lerp_c, loft, path_stations, smooth  # noqa: E402

# ---------------------------------------------------------------------------------------------
# The skeleton at rest (forward, up).

SIDE = 0.075
REST = {
    "pelvis": (-0.42, 0.93), "mid": (-0.08, 0.95), "chest": (0.24, 0.96), "neck": (0.36, 0.99),
    "skull": (0.60, 1.46), "nose": (0.88, 1.36), "jaw0": (0.63, 1.39), "jaw1": (0.85, 1.31),
    "tail0": (-0.53, 0.99), "tail1": (-0.58, 0.96), "tail2": (-0.62, 0.91), "tail3": (-0.64, 0.86),
    # Front leg: shoulder, elbow, knee (carpus), hoof. Hind: hip, stifle, hock, hoof.
    "shoulder": (0.25, 0.84), "elbow": (0.17, 0.63), "wrist": (0.22, 0.37), "fpaw": (0.25, 0.015),
    "hip": (-0.42, 0.88), "stifle": (-0.30, 0.64), "hock": (-0.50, 0.42), "hpaw": (-0.46, 0.015),
}
# The cannons turn with the leg as a hoof passes under the body (the legs are nearly straight).
SK = Skeleton(REST, SIDE, centre=(-0.09, 0.95), pastern_follow=0.85, neck_bend=0.9, head_bend=0.45, fore_fold=-1.0, fit=True, scapula=0.25)
body_pose, leg_points, neutral_paw, stand = SK.body_pose, SK.leg_points, SK.neutral_paw, SK.stand

# Head lowered to the grass (`body_pose`'s head[0]); raised and alert.
GRAZE, ALERT = 2.55, -0.05
# The tail: flagged up, and hanging.
FLAG, HANG = -1.6, 0.0


# ---------------------------------------------------------------------------------------------
# Clips: name -> (seconds, loop, natural speed m/s or None, function(t in 0..1) -> Pose)


def grazing(s, a=1.0):
    """Head down cropping at time `s` (s): the head jerks as it pulls grass, the jaw works."""
    crop = 0.5 + 0.5 * math.sin(2 * math.pi * s * 1.7)
    return (GRAZE * a + 0.06 * crop * a, 0.04 * a), 0.12 * crop * a, 0.12 * math.sin(2 * math.pi * s * 0.23) * a


IDLE_S = 10.0


def clip_idle(t):
    s = t * IDLE_S
    # 0–4.2 s grazing, raise by 5.0, up (chewing, looking round) until 8.6, lowered by 9.6.
    up = smooth((s - 4.2) / 0.8) * (1 - smooth((s - 8.6) / 1.0))
    (h0, h1), jaw, turn = grazing(s, 1 - up)
    look = 0.45 * bump(s, 5.3, 6.7) - 0.35 * bump(s, 7.0, 8.2)
    chew = 0.04 * (0.5 + 0.5 * math.sin(2 * math.pi * s * 2.2)) * up
    body = body_pose(bob=0.004 * math.sin(2 * math.pi * t * 2), pitch=0.07 * (1 - up), crouch=0.02 * (1 - up),
                     head=(h0 + (0.12 + ALERT * 0.0) * up, h1), head_turn=turn + look * up, jaw=jaw + chew,
                     tail=(HANG - 0.25 * bump(s, 6.0, 6.6), 0.5 * bump(s, 6.0, 6.6) * math.sin(2 * math.pi * s * 4)))
    return stand(body)


GRAZE_S = 4.0


def clip_graze(t):
    s = t * GRAZE_S
    (h0, h1), jaw, turn = grazing(s)
    body = body_pose(bob=0.004 * math.sin(2 * math.pi * t), pitch=0.07, crouch=0.02, head=(h0, h1), head_turn=turn + 0.1 * math.sin(2 * math.pi * t), jaw=jaw,
                     tail=(HANG, 0.15 * math.sin(2 * math.pi * t * 2)))
    return stand(body)


def clip_walk(t):
    a = 2 * math.pi * t
    body = body_pose(bob=0.012 * math.cos(2 * a), pitch=0.012 * math.sin(2 * a), head=(0.25 + 0.06 * math.cos(2 * a), 0.05),
                     head_turn=0.04 * math.sin(a), tail=(HANG, 0.12 * math.sin(a)))
    # Lateral sequence: left hind, left fore, right hind, right fore.
    return SK.gait(t, WALK, PERIOD["walk"], {"hl": 0.0, "fl": -0.25, "hr": -0.5, "fr": -0.75}, 0.6, 0.13, body, fold=0.9)


def clip_trot(t):
    a = 2 * math.pi * t
    body = body_pose(bob=0.028 * math.cos(2 * a), pitch=0.01 * math.sin(2 * a), head=(0.2, 0.05), tail=(HANG - 0.2, 0.08 * math.sin(a)))
    # Diagonal pairs together, a float between.
    return SK.gait(t, TROT, PERIOD["trot"], {"hl": 0.0, "fr": 0.0, "hr": -0.5, "fl": -0.5}, 0.4, 0.2, body, fold=1.2)


def clip_run(t):
    a = 2 * math.pi * t
    # A bound: the hind pair drives off nearly together, the back stretches through the air, the
    # fore pair lands and the back gathers the hind legs under it again. The tail is flagged.
    flex = 0.75 * math.cos(a)
    body = body_pose(bob=0.07 * math.sin(a + 0.8) + 0.03, pitch=-0.08 * math.sin(a), flex=flex, head=(0.3 - 0.1 * math.sin(a), 0.1),
                     tail=(FLAG, 0.05 * math.sin(a)))
    return SK.gait(t, RUN, PERIOD["run"], {"hl": 0.0, "hr": -0.05, "fl": -0.42, "fr": -0.5}, 0.28, 0.24, body, fold=1.4)


STARTLE_S = 0.6


def clip_startle(t):
    s = t * STARTLE_S
    # Head snaps up from wherever it was (it starts half lowered), the tail flags.
    head = lerp(1.2, ALERT - 0.15, smooth(s / 0.12))
    flag = smooth((s - 0.04) / 0.1)
    gather = smooth((s - 0.12) / 0.14) * (1 - smooth((s - 0.3) / 0.08))
    spring = bump(s, 0.3, 0.58)
    body = body_pose(bob=0.13 * spring - 0.02 * gather, crouch=0.07 * gather, pitch=-0.12 * gather + 0.04 * spring, flex=0.5 * gather - 0.3 * spring,
                     shift=0.08 * spring, head=(head, 0.0), head_turn=0.25 * bump(s, 0.02, 0.3), tail=(FLAG * flag, 0.0))
    p, place = body
    for leg in LEGS:
        f, u = neutral_paw(leg)
        front = LEGS[leg][0]
        # The hind hooves step under; in the spring the fore legs tuck and the hind push off.
        if front:
            leg_points(p, place, leg, (f + 0.05 * spring, u + 0.22 * spring), fold=1.2 * spring)
        else:
            leg_points(p, place, leg, (f + 0.08 * gather + 0.04 * spring, u + 0.08 * spring), fold=0.4 * spring)
    return p


HIT_S = 0.45


def clip_hit(t):
    s = t * HIT_S
    k = smooth(s / 0.07) * (1 - smooth((s - 0.12) / 0.3))
    body = body_pose(shift=-0.08 * k, crouch=0.05 * k, pitch=-0.06 * k, head=(-0.1 * k, -0.08 * k), head_turn=0.4 * k, jaw=0.15 * k, tail=(FLAG * 0.6 * k, 0.0))
    return stand(body)


DEATH_S = 1.6


def clip_death(t):
    s = t * DEATH_S
    buckle = smooth(s / 0.5)
    roll = smooth((s - 0.25) / 0.75)
    limp = smooth((s - 0.6) / 0.8)
    body = body_pose(crouch=0.32 * buckle, pitch=0.12 * buckle * (1 - roll), head=(0.9 * buckle, -0.05), jaw=0.12 * limp, tail=(HANG, 0.0))
    p, place = body
    for leg in LEGS:
        f, u = neutral_paw(leg)
        # The legs fold as it sinks, then lie loose and straighter.
        leg_points(p, place, leg, (f + (0.1 if LEGS[leg][0] else -0.08) * limp, u + 0.2 * buckle * (1 - limp) + 0.08 * limp), fold=0.7 * buckle * (1 - limp))
    return SK.lie_down(p, roll)


WALK, TROT, RUN = 1.3, 3.7, 4.6
PERIOD = {"walk": 1.0, "trot": 0.5, "run": 0.48}
# Gaits blend within this ratio either side of two neighbours' geometric mean (`gait.rs`).
BAND = 1.04
CLIPS = {
    "idle": (IDLE_S, True, None, clip_idle),
    "graze": (GRAZE_S, True, None, clip_graze),
    "walk": (PERIOD["walk"], True, WALK, clip_walk),
    "trot": (PERIOD["trot"], True, TROT, clip_trot),
    "run": (PERIOD["run"], True, RUN, clip_run),
    "startle": (STARTLE_S, False, None, clip_startle),
    "hit": (HIT_S, False, None, clip_hit),
    "death": (DEATH_S, False, None, clip_death),
}


# ---------------------------------------------------------------------------------------------
# Mesh

# Display (sRGB) colours, as written (see wolf.py).
COAT = (0.60, 0.41, 0.25)
BACK = (0.44, 0.30, 0.18)
PALE = (0.90, 0.84, 0.72)
WHITE = (0.96, 0.94, 0.89)
DARK = (0.07, 0.06, 0.06)
HOOF = (0.16, 0.13, 0.11)


def build_mesh(rest):
    bm = bmesh.new()
    parts = []
    J = lambda n: joint(rest, n)  # noqa: E731

    def torso_color(co, n):
        f, u = -co.y, co.z
        # Pale belly and throat, a darker back, a white rump patch.
        pale = smooth((-n.z - 0.25) / 0.45)
        back = smooth((n.z - 0.5) / 0.4)
        rump = smooth((-0.5 - f) / 0.06) * smooth((0.99 - u) / 0.06)
        c = lerp_c(lerp_c(COAT, BACK, back * 0.8), PALE, pale)
        return lerp_c(c, WHITE, rump)

    # Torso: rump to the base of the neck. Slim, with a deep chest and a tucked belly.
    pts = [P(-0.60, 0, 0.94), J("pelvis"), P(-0.26, 0, 0.955), J("mid"), P(0.08, 0, 0.955), J("chest"), P(0.36, 0, 0.98)]
    sizes = [(0.07, 0.08), (0.125, 0.155), (0.12, 0.14), (0.115, 0.15), (0.125, 0.18), (0.125, 0.2), (0.095, 0.15)]
    st = path_stations(pts, sizes)
    # The spine is the back line: the body hangs below it, the belly tucked behind the ribs.
    st = [(c + P(0, 0, -0.07) + (P(0, 0, 0.03) if i in (2, 3) else P(0, 0, -0.03) if i == 5 else P(0, 0, 0)), a, w, h) for i, (c, a, w, h) in enumerate(st)]
    v, f = loft(bm, st, sides=10)
    parts.append(Part(bm, v, f, ["hips", "spine", "chest", "tail1"], torso_color))

    # Neck: from inside the chest up to the back of the skull; a pale throat.
    def neck_color(co, n):
        throat = smooth((n.y * -1 - 0.1) / 0.5) * 0.0 + smooth((-n.z * 0.6 - n.y * 0.8 - 0.2) / 0.4)
        return lerp_c(lerp_c(COAT, BACK, smooth((n.z + n.y * 0.5 - 0.3) / 0.4) * 0.6), PALE, throat * 0.8)
    neck0, skull = J("neck"), J("skull")
    np_ = [neck0 + P(-0.1, 0, -0.02), neck0, lerp(neck0, skull, 0.35), lerp(neck0, skull, 0.7), skull + P(-0.03, 0, -0.02)]
    v, f = loft(bm, path_stations(np_, [(0.09, 0.13), (0.085, 0.12), (0.064, 0.082), (0.05, 0.064), (0.046, 0.052)]), sides=8)
    parts.append(Part(bm, v, f, ["chest", "neck", "head"], neck_color))

    # Head: a long tapering muzzle with a dark nose, and the lower jaw.
    def head_color(co, n):
        f = -co.y
        pale = smooth((-n.z + 0.15) / 0.4) * 0.7
        c = lerp_c(COAT, PALE, pale)
        return lerp_c(c, DARK, smooth((f - 0.86) / 0.02))
    nose = J("nose")
    hp = [skull + P(-0.06, 0, 0.0), skull + P(0.02, 0, 0.0), lerp(skull, nose, 0.45), lerp(skull, nose, 0.8), nose + P(0.0, 0, 0.005)]
    hs = [(0.05, 0.06), (0.062, 0.065), (0.045, 0.048), (0.032, 0.035), (0.024, 0.026)]
    v, f = loft(bm, path_stations(hp, hs), sides=8)
    parts.append(Part(bm, v, f, ["head"], head_color))
    jp = [J("jaw0"), lerp(J("jaw0"), J("jaw1"), 0.5), J("jaw1")]
    v, f = loft(bm, path_stations(jp, [(0.035, 0.016), (0.028, 0.014), (0.018, 0.01)]), sides=6)
    parts.append(Part(bm, v, f, ["jaw"], lambda co, n: PALE))
    # Nose tip and eyes.
    hd = (nose - skull).normalized()
    for c, r, col in [(nose + hd * 0.012 + P(0, 0, 0.006), 0.02, DARK)] + [(skull + hd * 0.1 + P(0, s * 0.046, 0.03), 0.013, DARK) for s in (-1, 1)]:
        g = bmesh.ops.create_icosphere(bm, subdivisions=1, radius=r)
        bmesh.ops.translate(bm, vec=c, verts=g["verts"])
        parts.append(Part(bm, g["verts"], list({fc for vv in g["verts"] for fc in vv.link_faces}), ["head"], lambda co, n, col=col: col))
    # Ears: big leaves held out and up, pale inside, dark rims.
    for s in (-1, 1):
        base = skull + P(-0.02, s * 0.035, 0.05)
        out = P(-0.03, s * 0.17, 0.13)
        w = P(0.0, 0, 0.0)
        quad = [base + P(0.025, 0, -0.005), base + out * 0.5 + P(0.04, 0, 0.035) + w, base + out, base + out * 0.5 + P(-0.04, 0, -0.03), base + P(-0.025, 0, 0.005)]
        thick = P(0.012, 0, 0)
        front = [bm.verts.new(q + thick) for q in quad]
        back = [bm.verts.new(q - thick) for q in quad]
        fs = [bm.faces.new(front), bm.faces.new(list(reversed(back)))]
        for i in range(len(quad)):
            j = (i + 1) % len(quad)
            fs.append(bm.faces.new((front[i], back[i], back[j], front[j])))
        parts.append(Part(bm, front + back, fs, ["head"], lambda co, n: lerp_c(lerp_c(COAT, BACK, 0.3), PALE, smooth((-n.y - 0.2) / 0.5) * 0.7)))

    # Legs: long and thin, dark hooves.
    for leg, (front, sgn) in LEGS.items():
        names = ("shoulder", "elbow", "wrist", "fpaw") if front else ("hip", "stifle", "hock", "hpaw")
        q = [J(f"{leg}.{nm}") for nm in names]
        top = q[0] + P(0, 0, 0.07)
        cannon = lerp(q[2], q[3], 0.55)
        pts = [top, q[0], q[1], lerp(q[1], q[2], 0.5), q[2], cannon, q[3] + P(-0.01, 0, 0.05), q[3] + P(0.005, 0, 0.012)]
        if front:
            sz = [(0.055, 0.1), (0.055, 0.085), (0.04, 0.05), (0.03, 0.036), (0.024, 0.027), (0.016, 0.019), (0.02, 0.021), (0.022, 0.024)]
            bones = ["chest", f"upper.{leg}", f"fore.{leg}", f"paw.{leg}"]
        else:
            sz = [(0.065, 0.13), (0.07, 0.125), (0.045, 0.065), (0.032, 0.042), (0.024, 0.03), (0.016, 0.019), (0.02, 0.021), (0.022, 0.024)]
            bones = ["hips", f"thigh.{leg}", f"shin.{leg}", f"paw.{leg}"]

        def leg_color(co, n, sgn=sgn):
            u = co.z
            inner = smooth((-(n.x * sgn) - 0.1) / 0.5)
            c = lerp_c(COAT, PALE, 0.55 * inner + 0.35 * smooth((0.45 - u) / 0.2))
            return lerp_c(c, HOOF, smooth((0.06 - u) / 0.02))
        v, f = loft(bm, path_stations(pts, sz), sides=7)
        parts.append(Part(bm, v, f, bones, leg_color))

    # Tail: short and flat, white beneath (it shows when the tail flags).
    tp = [J("tail0") + P(0.02, 0, 0.0), J("tail1"), J("tail2"), J("tail3"), J("tail3") + (J("tail3") - J("tail2")) * 0.4]
    ts = [(0.035, 0.03), (0.05, 0.03), (0.05, 0.028), (0.04, 0.022), (0.012, 0.01)]
    v, f = loft(bm, path_stations(tp, ts), sides=7)
    parts.append(Part(bm, v, f, ["hips", "tail1", "tail2", "tail3"],
                      lambda co, n: lerp_c(BACK, WHITE, smooth((-n.z + 0.1) / 0.4))))
    return bm, parts


def main():
    a = args()

    def extra(name, rec):
        if name == "run":
            rec["gait"] = "bound"

    summary = build(SK, "deer", CLIPS, build_mesh, a.out, None, (0.1, 0.35), extra=extra, stretch=True)
    if summary is not None and a.summary:
        import json
        summary["band"] = BAND
        with open(a.summary, "w") as f:
            json.dump(summary, f, indent=1)


main()
