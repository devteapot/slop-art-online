"""Clip lab: generate Kimodo takes for a clip library entry, score every take on the raw motion,
pick one by a stated rule, and report why.

    PY=~/kimodo-test/venv/bin/python          # numpy and Pillow; generation runs batch.py in it
    $PY living/tools/kimodo/cliplab.py --clip work --prompt "…" [--prompt "…"] --seconds 6 --seeds 8
    $PY living/tools/kimodo/cliplab.py --clip work,play --score-only
    $PY living/tools/kimodo/cliplab.py --clip work --write          # adopt the last run's winner
    $PY living/tools/kimodo/cliplab.py --handoff A --clip turn_left_90,…  # tarball for the laptop

The entry comes from `clips.json` (`--clips`), changed by `--prompt` (repeatable: one variant per
prompt), `--seconds` and `--set KEY=JSON` (e.g. `--set 'path=[[0,0,0],[4,0,0]]'`, `--set end=null`).
Each variant is generated for `--seeds N` new seed numbers (a block of ten per variant above every
seed already used for the name), so no library take is overwritten and the chosen variant can be
regenerated from its entry by batch.py. Takes go to `--out` (default `~/cliplab`), `<clip>/takes`.
Generation waits until no other Kimodo `batch.py` runs and 40 GB of RAM would stay free, and runs
under `nice`. The entry's current library takes (`--lib`) are scored with the new ones, so a new
take wins only by scoring better than the old pick.

Scores (raw SOMA-77 NPZ, Kimodo's metres, 30 fps; limits in LIMITS, set on the 2026-11-11 library.
There, 14 of the 32 Kimodo picks fail a check: the five weak takes the lab was made for (work,
play, sit_ground_down, sit_ground, stand_up_ground); the calm loops idle and sit_idle (frozen by
design: score them with `--expect active_share>=0 --expect frozen_s<=6`) and listen (active 41 %);
death (a fall: body 22 cm, palms 5 cm under the floor); run and run_fast (loop velocity 0.61 and
0.87 m/s at their best cycle); hit, sword_slash and sword_thrust (slide, or toes 2.6-3.3 cm under)):
- floor: how far hands (wrist, palm and knuckles: rigid with the hand), feet and the rest of the
  body go below y = 0 (cm);
  fingertips are scored softly (Kimodo's fingers hang relaxed, so a palm on the floor puts them
  through it: retargeting has to bend them, the take cannot);
- slide: 90th percentile speed of heels and toes while Kimodo flags them planted (cm/s; gaits and
  one-shots that travel or turn get GAIT_SLIDE_CM_S), and the largest drift over one contact (cm);
- active: share of frames where the fastest extremity (head top, hands, toe tips) moves at least
  ACTIVE_M_S about the hips (0.5 s mean); frozen: the longest stretch below STILL_M_S (a one-shot
  may stand still at its ends); not checked for gaits and falls;
- pop: the largest one-frame change of a joint's velocity about the hips (soft: penalty only);
- loop closure (`kind: loop`): pose (cm) and velocity (m/s) mismatch about the hips between the
  ends of a `whole` loop, or of the best cycle in `cycle: [min, max]` after `skip`;
- start/end keyframe: batch.py's keyframe pose (`end_offset`, `end_yaw`) against the take (cm);
- path: the hips off the entry's `path` (cm; the last 0.15 s is left out when the entry's end
  keyframe and path disagree, which is reported once as an entry warning);
- travel: a one-shot's end displacement against `path`/`end_offset` (in place when keyed at both
  ends; unchecked when it ends unkeyed, as sitting down); a loop's speed against its `path` and
  its travel direction against `travel_deg` (0 ahead, 180 back, -90 left, 90 right);
- turn: heading change against `turn_deg` (or -`end_yaw`; 0 for one-shots that end unkeyed);
  facing: drift of the chest's heading in gaits and in one-shots that travel without turning;
- cadence: step period against the library's forward pick of the same gait (walk, run, sneak);
  or of the entry's `cadence_ref` (the forward take made for the same speed; a forward take names
  itself and is not checked);
- planted slide (gaits; **the gate for gaits**, checked for every gait at 4 cm): `plant_slide_cm`,
  the game's marker_check.py slide emulated on the raw take driven at the entry's `game_speed`
  (game m/s on Vivi; default the take's own speed). Per plant, the slower of the heel point and
  the ball is followed against the ground and its movement summed; the worst plant counts. It is
  a distance per plant, not a share of speed. `plants` (how many each foot has), and
  `plant_frames_min` and `plant_frames_med` (game frames; check `--expect 'plant_frames_min>=4'`)
  come from the same emulated markers: a take scaled past its own speed loses its short plants.
  The raw number reads lower than the laptop's on the baked clip (see docs/GAME_BRIEF.md), so
  marker_check on the bake stays the final word;
- toe slide (gaits; reported, check it with `--expect 'toe_slide_pct<=5'`): the slower toe near the
  floor as a share of the body's speed (median), the laptop's no-slide line; air_share: flight;
- air (`hop` or a name starting with jump): the longest stretch with both feet off the ground;
  hop: its overlap (intersection over union) with the entry's `hop` window.
Reported, not checked: steps, head_turn_deg, hand_path_m, hips_drop_m, air_window_s and more.
`--expect METRIC>=X` (or `<=`) adds a check or replaces a limit, e.g. `head_turn_deg>=25` for a
look-around or `active_share>=0.3` for a calm loop.

Pick rule: a take is eligible when it fails no check. Each check gives a ratio r (measured over
limit, or limit over measured for a minimum), fail when r > 1; the penalty is the sum of min(r, 3).
The winner is the eligible take with the lowest penalty (ties: the library take, then the lower
seed). When no take passes, the one with the fewest failed checks, then the lowest penalty, is
reported as the best of a failing set.

Known limit of the motion model (measured 2026-11-11, speed takes): a clean run above about
4 m/s raw is beyond Kimodo. With the forward run pinned to a path, 13 of 84 takes hold the 5 % toe
line at 3.8 m/s raw (3.63 on Vivi), 1 of 40 at 4.0 (its toes 2.6 cm under the floor), and 0 of 130
from 4.2 to 5.03 m/s raw, 74 of them at the 5.03 the rules' 4.8 m/s run needs (7 prompts, guidance
1-3.5, a ramped path, an 8 s take: the foot skims the floor at body speed before it plants and the
hips bound 20-140 cm). Unpinned, a fast run levels off at 3.5-3.7 m/s raw. Backward and sideways
runs hold the line at no speed from 2.6 to 3.8 (0 of 132; best 5.6-8 %). The best clean run is
run_v48 s0 (3.63 m/s natural on Vivi, run_fast's metres a cycle). A faster run needs another
source: retiming (the bake's --target), another generator, or hand keys. Do not ask Kimodo again;
the table is in docs/GAME_BRIEF.md (Clip lab, Kimodo's speed ceiling).
The walk has a ceiling as well: a clean true walk (no flight, toe line held) stops at about 3.0 m/s
on Vivi (3.14 raw: 1 of 88 passes; 3.28 to 3.56 raw: 0 of 192). Open goal: a clean, loopable run
stride longer than 2.8 m a cycle raw; what was tried (faster paths, prompts, a 96-take search for
the stride) and what was not (footfall constraints, stride lengthening in the bake) is listed in
docs/GAME_BRIEF.md beside the ceiling table. Keep an entry's `cycle` upper bound under twice its
step period, or the bake may cut two strides.

Writes `<out>/<clip>/checks.json` (entry, limits, every take's metrics, checks and penalty, the
winner and why), `<out>/<clip>/sheet.png` (every take: front and side poses, and the motion-energy
curve with the active line), `<out>/<clip>/pick.png`, and appends a line to `<out>/report.md`.
"""

import argparse
import datetime
import fcntl
import hashlib
import io
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tarfile
import time

import numpy as np
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
FPS = 30
VENV_PY = os.path.expanduser("~/kimodo-test/venv/bin/python")
LOCK = "/tmp/kimodo-gpu.lock"
DEFAULT_LIB = os.path.expanduser("~/dev/slop-art-online-t3/.local/kimodo/outputs/library")

HIPS, HEAD, HEADEND, LHAND, RHAND = 0, 6, 7, 14, 42
LSHO, RSHO, LLEG, RLEG = 11, 39, 67, 72
LFOOT, LTOE, LTOEEND, RFOOT, RTOE, RTOEEND = 69, 70, 71, 74, 75, 76
FINGERS = list(range(15, 39)) + list(range(43, 67))
# each finger's SOMA ...1 joint (metacarpal, inside the palm) and ...2 joint (the knuckle, where
# animate.py's J_Bip finger starts): rigid with the hand, so the take, not retargeting, places them
KNUCKLES = [15, 19, 24, 29, 34, 43, 47, 52, 57, 62] + [16, 20, 25, 30, 35, 44, 48, 53, 58, 63]
HANDS = [LHAND, RHAND] + KNUCKLES  # where the hand is: wrist, palm and knuckles
FINGERTIPS = [j for j in FINGERS if j not in KNUCKLES]  # Kimodo's fingers hang relaxed: the rest
# go through the floor when a palm is on it, which retargeting has to fix, not the take
FEET = [LFOOT, LTOE, LTOEEND, RFOOT, RTOE, RTOEEND]
BODY = [i for i in range(77) if i not in FINGERS]  # everything but the fingers
OTHER = [i for i in range(77) if i not in HANDS + FINGERTIPS and i not in FEET]
CONTACT = [(0, LFOOT), (1, LTOE), (3, RFOOT), (4, RTOE)]  # foot_contacts columns: heels, toes

EXTREMITIES = [HEADEND, LHAND, RHAND, LTOEEND, RTOEEND]
ACTIVE_M_S = 0.15  # the fastest extremity's speed about the hips (0.5 s mean) that counts as doing something
STILL_M_S = 0.04  # below this the pose is frozen
LIMITS = {  # check: (metric, limit, "max" | "min")
    "floor_hands": ("floor_hands_cm", 2.0, "max"),
    "floor_feet": ("floor_feet_cm", 2.0, "max"),
    "floor_body": ("floor_body_cm", 2.0, "max"),
    "floor_fingers": ("floor_fingers_cm", 2.0, "max"),  # soft: see FINGERTIPS
    "slide": ("slide_p90_cm_s", 6.0, "max"),
    "drift": ("drift_max_cm", 6.0, "max"),
    "pop": ("pop_m_s", 1.5, "max"),  # soft: adds to the penalty, never fails (fast swings reach it too)
    "active": ("active_share", 0.6, "min"),
    "frozen": ("frozen_s", 1.0, "max"),
    "loop_pose": ("loop_pose_cm", 8.0, "max"),  # animate.py spreads the rest over the loop
    "loop_vel": ("loop_vel_m_s", 0.6, "max"),
    "start_key": ("start_err_cm", 3.0, "max"),
    "end_key": ("end_err_cm", 3.0, "max"),
    "path": ("path_err_cm", 6.0, "max"),
    "travel": ("travel_err_m", None, "max"),  # limit per take: max(0.12 m, 12 % of the expected travel)
    "travel_dir": ("travel_dir_err_deg", 15.0, "max"),
    "turn": ("turn_err_deg", 12.0, "max"),
    "facing": ("facing_drift_deg", 15.0, "max"),
    "cadence": ("cadence_err", 0.12, "max"),
    "plant_slide": ("plant_slide_cm", 4.0, "max"),  # gaits: marker_check.py's SLIDE_M, on the raw take (see measure)
    "air": ("air_s", 0.2, "min"),  # jumps (a `hop` window or a name starting with jump)
    "hop": ("hop_iou", 0.7, "min"),  # the airborne stretch against the entry's `hop` [t0, t1]
}
SOFT = {"pop", "floor_fingers"}
TOE_REST_M = 0.02  # the toe joint's height standing (stand#3)
# marker_check.py's heel point (under the ankle at the ball's height, a quarter of the foot behind
# the ankle), in each ankle joint's own frame, from the neutral pose stand#3@45
HEEL_IN_ANKLE = {"L": (0.0032, -0.0501, -0.0332), "R": (-0.0007, -0.0506, -0.0333)}
K_GAME = 0.955  # game metres per SOMA metre on Vivi (a path-pinned take's baked natural speed over its raw speed; Shino 0.985, own-man 0.93)
GAIT_SLIDE_CM_S = 10.0  # a gait's contacts include touchdown and toe-off frames; a turn's heels sweep about the ball


# ---------------------------------------------------------------------------------------------
# Geometry


def heading(p):
    """Kimodo's heading of one posed frame (77 x 3): 0 faces +Z, positive turns to the body's left (+X)."""
    d = p[RLEG] - p[LLEG]
    return math.atan2(d[2], -d[0])


def headings(P, a=LLEG, b=RLEG):
    d = P[:, b] - P[:, a]
    return np.unwrap(np.arctan2(d[:, 2], -d[:, 0]))


def yaw(phi):
    c, s = math.cos(phi), math.sin(phi)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])


def turned(q, turn):
    """q (hips at the origin) turned about the vertical so its heading becomes heading(q) + turn."""
    for phi in (turn, -turn):
        t = q @ yaw(phi).T
        if abs(math.remainder(heading(t) - heading(q) - turn, 2 * math.pi)) < 1e-3:
            return t
    raise SystemExit(f"could not turn a pose by {turn}")


def load(path):
    d = np.load(path)
    return {"P": d["posed_joints"].astype(np.float64), "root": d["root_positions"].astype(np.float64),
            "fc": d["foot_contacts"].astype(bool), "R": d["local_rot_mats"].astype(np.float64),
            "G": d["global_rot_mats"].astype(np.float64)}


def ref_pose(spec, neutral, dirs, offset=(0.0, 0.0), turn_deg=0.0):
    """batch.py's keyframe for `spec` as posed joints: facing +Z (then turned by `turn_deg`, + to
    the left), hips at (offset x, its own height, offset z)."""
    if spec == "neutral":
        spec = neutral
    ns, frame = spec.split("@")
    name, seed = ns.split("#")
    path = find(dirs, f"{name}_s{int(seed)}.npz")
    d = load(path)
    f = int(frame) % len(d["P"])
    p, root = d["P"][f], d["root"][f]
    q = turned(p - root, -heading(p))
    if turn_deg:
        q = turned(q, math.radians(turn_deg))
    return q + np.array([offset[0], root[1], offset[1]])


def find(dirs, fname):
    for d in dirs:
        p = os.path.join(d, fname)
        if os.path.exists(p):
            return p
    raise SystemExit(f"{fname} not found in {dirs}")


def runs(mask):
    out, start = [], None
    for i, m in enumerate(mask):
        if m and start is None:
            start = i
        if not m and start is not None:
            out.append((start, i - 1))
            start = None
    if start is not None:
        out.append((start, len(mask) - 1))
    return out


def smooth(x, n):
    if len(x) < n:
        return np.full_like(x, x.mean())
    k = np.ones(n) / n
    pad = np.pad(x, (n // 2, n - 1 - n // 2), mode="edge")
    return np.convolve(pad, k, mode="valid")


def local_frames(P, root):
    """Each frame's body about its hips, faced to +Z: (T, 77, 3)."""
    h = headings(P)
    out = np.empty_like(P)
    for f in range(len(P)):
        q = P[f] - np.array([root[f, 0], 0.0, root[f, 2]])
        c, s = math.cos(-h[f]), math.sin(-h[f])
        R = np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])
        out[f] = q @ R.T
    return out


def period(sig, lo=8, hi=None):
    """Fundamental period (frames) of a signal: the first autocorrelation peak near the best one."""
    s = sig - sig.mean()
    n = len(s)
    hi = min(hi or n // 2, n - 2)
    if hi <= lo or not np.any(s):
        return None
    ac = np.array([np.dot(s[:n - k], s[k:]) / (n - k) for k in range(hi + 1)])
    ac /= ac[0]
    peaks = [k for k in range(lo, hi) if ac[k] > ac[k - 1] and ac[k] >= ac[k + 1] and ac[k] > 0.2]
    if not peaks:
        return None
    top = max(ac[k] for k in peaks)
    k = next(k for k in peaks if ac[k] >= 0.8 * top)
    y0, y1, y2 = ac[k - 1], ac[k], ac[k + 1]
    den = y0 - 2 * y1 + y2
    return k + (0.5 * (y0 - y2) / den if den else 0.0)


# ---------------------------------------------------------------------------------------------
# What an entry asks for


def travels(e):
    """A one-shot that moves the body along a path (starts, stops, jumps): it slides like a gait."""
    p = e.get("path")
    return bool(p) and math.hypot(p[-1][1] - p[0][1], p[-1][2] - p[0][2]) > 0.3


def lint(e, frames):
    """Problems of the entry itself, the same for every take."""
    out = []
    p = e.get("path")
    if p and e.get("end"):
        t = (frames - 1) / FPS
        if p[-1][0] >= t:
            x, z = (float(np.interp(t, [q[0] for q in p], [q[i] for q in p])) for i in (1, 2))
            ox, oz = e.get("end_offset", (0.0, 0.0))
            gap = math.hypot(x - ox, z - oz)
            if gap > 0.03:
                out.append(f"end_offset {[ox, oz]} is {100 * gap:.1f} cm from the path at the last frame ({t:.3f} s, "
                           f"{[round(x, 3), round(z, 3)]}): the path runs to {p[-1][0]} s but the last frame is {t:.3f} s; "
                           "the hips follow the end keyframe, so they jump that far ahead of the path in the last frames")
    return out


def family(e):
    """The forward gait whose cadence a locomotion take should keep: walk, run, sneak or None."""
    if e.get("locomotion"):
        return e["locomotion"]
    n = e["name"]
    if e.get("kind") != "loop" or "travel_deg" not in e and "path" not in e:
        return None
    for f in ("run", "walk", "sneak"):
        if f in n:
            return f
    return None


def expected(e):
    """Travel (x, z in SOMA metres over the clip, or a speed for loops), travel direction and turn."""
    x = {"turn_deg": None, "travel": None, "speed": None, "travel_deg": e.get("travel_deg")}
    if "turn_deg" in e:
        x["turn_deg"] = float(e["turn_deg"])
    elif "end_yaw" in e:
        x["turn_deg"] = -float(e["end_yaw"])
    path = e.get("path")
    if e.get("kind") == "loop":
        if path and path[-1][0] > path[0][0]:
            d = np.hypot(path[-1][1] - path[0][1], path[-1][2] - path[0][2])
            x["speed"] = d / (path[-1][0] - path[0][0])
        if x["travel_deg"] is None and (e.get("locomotion") or path):
            x["travel_deg"] = 0.0
        return x
    if path:
        x["travel"] = (path[-1][1] - path[0][1], path[-1][2] - path[0][2])
    elif e.get("end"):
        x["travel"] = tuple(e.get("end_offset", (0.0, 0.0)))
    # else: a one-shot that ends where it ends (sitting down): travel is reported, not checked
    if x["turn_deg"] is None and not e.get("end") and e.get("plant") is not False:
        x["turn_deg"] = 0.0  # ends unkeyed: it should keep facing ahead (a fall may turn)
    return x


# ---------------------------------------------------------------------------------------------
# Measuring one take


def measure(e, take, lib, dirs, refs):
    d = load(take)
    P, root, fc = d["P"], d["root"], d["fc"]
    T = len(P)
    m = {"frames": T, "seconds": round(T / FPS, 2)}
    kind = e.get("kind")

    def floor(idx):
        return round(max(0.0, -100 * float(P[:, idx, 1].min())), 1)
    m["floor_hands_cm"], m["floor_feet_cm"], m["floor_body_cm"] = floor(HANDS), floor(FEET), floor(OTHER)
    m["floor_fingers_cm"] = floor(FINGERTIPS)
    m["floor_frames"] = int((P[:, :, 1] < -0.01).any(axis=1).sum())
    m["floor_worst"] = f"j{int(P[:, :, 1].min(axis=0).argmin())} f{int(P[:, :, 1].min(axis=1).argmin())}"

    speeds, drifts = [], []
    for col, j in CONTACT:
        v = np.zeros(T)
        v[1:] = np.hypot(*(P[1:, j, [0, 2]] - P[:-1, j, [0, 2]]).T) * FPS
        for a, b in runs(fc[:, col]):
            if b > a:
                speeds.extend(v[a + 1:b + 1])
                drifts.append(float(np.hypot(*(P[b, j, [0, 2]] - P[a, j, [0, 2]]))))
    m["contact_share"] = round(float(fc[:, [0, 1, 3, 4]].mean()), 2)
    m["slide_med_cm_s"] = round(100 * float(np.median(speeds)), 1) if speeds else 0.0
    m["slide_p90_cm_s"] = round(100 * float(np.percentile(speeds, 90)), 1) if speeds else 0.0
    m["drift_max_cm"] = round(100 * max(drifts), 1) if drifts else 0.0

    rel = P[:, BODY] - root[:, None, :]
    energy = np.linalg.norm(np.gradient(P[:, EXTREMITIES] - root[:, None, :], axis=0) * FPS, axis=2).max(axis=1)
    es = smooth(energy, FPS // 2)
    m["energy_median_m_s"] = round(float(np.median(es)), 3)
    m["active_share"] = round(float((es >= ACTIVE_M_S).mean()), 2)
    hv = np.linalg.norm(np.gradient(P[:, [LHAND, RHAND]] - root[:, None, :], axis=0) * FPS, axis=2)
    m["both_hands_active_share"] = round(float((smooth(hv.min(axis=1), FPS // 2) >= ACTIVE_M_S).mean()), 2)
    # a one-shot may stand still before it starts and after it ends; a loop has no such ends
    still = [(a, b) for a, b in runs(es < STILL_M_S) if kind == "loop" or (a > 0 and b < T - 1)]
    m["frozen_s"] = round(max([(b - a + 1) / FPS for a, b in still], default=0.0), 2)
    wv = np.diff(rel, axis=0) * FPS  # about the hips: a path's speed step or a foot strike is not a pop
    acc = np.linalg.norm(np.diff(wv, axis=0), axis=2)
    m["pop_m_s"] = round(float(acc.max()), 2)
    m["pop_at"] = f"f{int(np.unravel_index(acc.argmax(), acc.shape)[0]) + 1} j{BODY[int(np.unravel_index(acc.argmax(), acc.shape)[1])]}"

    loc = local_frames(P, root)
    hh = headings(P)
    head = headings(P, 9, 10)  # the eyes' line: where the head looks
    m["head_turn_deg"] = round(math.degrees(float(np.ptp(head - hh))), 1)
    m["hand_path_m"] = round(float(sum(np.linalg.norm(np.diff(rel[:, BODY.index(j)], axis=0), axis=1).sum() for j in (LHAND, RHAND))), 2)
    m["hips_drop_m"] = round(float(root[0, 1] - root[:, 1].min()), 2)
    m["hips_rise_cm"] = round(100 * float(root[:, 1].max() - root[0, 1]), 1)  # a jump's height
    # posture: mean heights of the hips and the hands (standing: 0.99 and 0.86 m; walk#1: 0.97 and 0.85)
    m["hips_y_mean_m"] = round(float(root[:, 1].mean()), 3)
    m["hands_y_mean_m"] = round(float(P[:, [LHAND, RHAND], 1].mean()), 2)

    # posture in the body's own frame (faced ahead): + leans forward. Standing: torso -2, head 8 degrees
    tv_ = loc[:, 4] - loc[:, HIPS]
    m["torso_pitch_deg"] = round(float(np.degrees(np.arctan2(tv_[:, 2], tv_[:, 1])).mean()), 1)
    hv_ = loc[:, HEAD] - loc[:, 3]
    m["head_pitch_deg"] = round(float(np.degrees(np.arctan2(hv_[:, 2], hv_[:, 1])).mean()), 1)
    # hands at work in front: both 0.75-1.25 m up and 15 cm or more ahead of the hips, one moving
    hy, hz = P[:, [LHAND, RHAND], 1], loc[:, [LHAND, RHAND], 2] - loc[:, [HIPS], 2]
    at = ((hy > 0.75) & (hy < 1.25) & (hz > 0.15)).all(axis=1)
    hs_ = smooth(np.linalg.norm(np.gradient(P[:, [LHAND, RHAND]] - root[:, None, :], axis=0) * FPS, axis=2).max(axis=1), FPS // 2)
    m["bench_busy_share"] = round(float((at & (hs_ >= ACTIVE_M_S)).mean()), 2)
    # how far the shoulders' midpoint moves about the hips (a weight shift, a lean): its largest range
    mid = (loc[:, LSHO] + loc[:, RSHO]) / 2 - loc[:, HIPS]
    m["shoulder_range_cm"] = round(100 * float(np.ptp(mid, axis=0).max()), 1)
    # seated: hips below 0.55 m (standing 0.99, cross-legged 0.16). The ankles' lowest height then
    # (standing 7 cm): lower means the foot is pressed into the floor
    seated = root[:, 1] < 0.55
    m["seated_share"] = round(float(seated.mean()), 2)
    if seated.any():
        m["seated_feet_min_cm"] = round(100 * float(P[seated][:, [LFOOT, RFOOT], 1].min()), 1)

    if kind == "loop":
        lv = np.gradient(loc[:, BODY], axis=0) * FPS
        if e.get("cycle") == "whole":
            a, b = 0, T - 1
        else:
            lo, hi = (round(s * FPS) for s in e.get("cycle", (1.0, 3.0)))  # animate.py's default
            best = None
            for a in range(min(round(e.get("skip", 0) * FPS), T - 2), T - lo):
                for L in range(lo, min(hi, T - 1 - a) + 1):
                    pe = np.linalg.norm(loc[a, BODY] - loc[a + L, BODY], axis=1).max()
                    ve = np.linalg.norm(lv[a] - lv[a + L], axis=1).max()
                    sc = pe + 0.05 * ve
                    if best is None or sc < best[0]:
                        best = (sc, a, a + L)
            a, b = (best[1], best[2]) if best else (0, T - 1)
        m["loop_frames"] = [a, b]
        m["loop_pose_cm"] = round(100 * float(np.linalg.norm(loc[a, BODY] - loc[b, BODY], axis=1).max()), 1)
        m["loop_vel_m_s"] = round(float(np.linalg.norm(lv[a] - lv[b], axis=1).max()), 2)
        # the seam's largest joint rotation difference (local rotations, the hips' own left out: they
        # carry the heading); what the loop's closing has to spread
        Ra, Rb = d["R"][a, BODY[1:]], d["R"][b, BODY[1:]]
        cos = (np.einsum("jik,jik->j", Ra, Rb) - 1) / 2
        m["loop_seam_deg"] = round(float(np.degrees(np.arccos(np.clip(cos, -1, 1))).max()), 1)

    neutral = lib.get("neutral")
    if e.get("start"):
        r = ref_pose(e["start"], neutral, refs)
        m["start_err_cm"] = round(100 * float(np.linalg.norm(P[0, BODY] - r[BODY], axis=1).max()), 1)
    if e.get("end"):
        r = ref_pose(e["end"], neutral, refs, e.get("end_offset", (0.0, 0.0)), e.get("end_yaw", 0.0))
        m["end_err_cm"] = round(100 * float(np.linalg.norm(P[-1, BODY] - r[BODY], axis=1).max()), 1)
    path = e.get("path")
    if path:
        ts = [q[0] for q in path]
        t = np.arange(T) / FPS
        ok = (t >= ts[0]) & (t <= ts[-1] + 1e-6)
        if lint(e, T):  # the end keyframe and the path disagree: judge the path short of the end
            ok &= t < (T - 1) / FPS - 0.15
        err = np.hypot(root[:, 0] - np.interp(t, ts, [q[1] for q in path]), root[:, 2] - np.interp(t, ts, [q[2] for q in path]))[ok]
        m["path_err_cm"] = round(100 * float(err.max()), 1)

    # feet: down when Kimodo says so or the foot is at the floor; a step is a foot moving > 8 cm
    down = {}
    for side, heel, toe, c0, c1 in (("L", LFOOT, LTOE, 0, 1), ("R", RFOOT, RTOE, 3, 4)):
        down[side] = fc[:, c0] | fc[:, c1] | (P[:, toe, 1] < 0.045) | (P[:, heel, 1] < 0.095)
    air = ~(down["L"] | down["R"])
    air_runs = [(a, b) for a, b in runs(air) if b > a]
    m["air_s"] = round(max([(b - a + 1) / FPS for a, b in air_runs], default=0.0), 2)
    m["hops"] = sum(1 for a, b in air_runs if b - a + 1 >= 3)  # airborne for 0.1 s or more
    if air_runs:
        a, b = max(air_runs, key=lambda r: r[1] - r[0])
        m["air_window_s"] = [round(a / FPS, 2), round((b + 1) / FPS, 2)]
        if e.get("hop"):
            h0, h1 = e["hop"]
            t0, t1 = a / FPS, (b + 1) / FPS
            inter = max(0.0, min(t1, h1) - max(t0, h0))
            m["hop_iou"] = round(inter / (max(t1, h1) - min(t0, h0)), 2)
    elif e.get("hop"):
        m["hop_iou"] = 0.0
    # how high both feet get (the lower foot's lowest joint), and whether the feet cross: the left
    # foot's ankle against the right's along the body's left (negative: crossed)
    m["feet_clear_cm"] = round(100 * float(np.minimum(P[:, FEET[:3], 1].min(1), P[:, FEET[3:], 1].min(1)).max()), 1)
    left = np.stack([np.cos(hh), -np.sin(hh)], axis=1)
    m["feet_gap_min_cm"] = round(100 * float(np.einsum("ij,ij->i", P[:, LFOOT, [0, 2]] - P[:, RFOOT, [0, 2]], left).min()), 1)
    # a step: a foot moving (heel or toe tip faster than 0.4 m/s) that ends > 8 cm away or turned > 20 degrees
    steps = []
    for side, heel, toe in (("L", LFOOT, LTOEEND), ("R", RFOOT, RTOEEND)):
        v = np.zeros(T)
        for j in (heel, toe):
            v[1:] = np.maximum(v[1:], np.hypot(*(P[1:, j, [0, 2]] - P[:-1, j, [0, 2]]).T) * FPS)
        for a, b in runs(v > 0.4):
            a0 = max(a - 1, 0)
            f0, f1 = P[a0, toe] - P[a0, heel], P[b, toe] - P[b, heel]
            turn_f = abs(math.degrees(math.remainder(math.atan2(f1[0], f1[2]) - math.atan2(f0[0], f0[2]), 2 * math.pi)))
            if np.hypot(*(P[b, heel, [0, 2]] - P[a0, heel, [0, 2]])) > 0.08 or turn_f > 20:
                steps.append((a, side))
    steps.sort()
    m["steps"] = len(steps)
    m["step_feet"] = "".join(s for _, s in steps)
    m["first_step_right"] = int(bool(steps) and steps[0][1] == "R")

    x = expected(e)
    hs = smooth(hh, FPS)  # an unkeyed end is read over a stride: the pelvis swings about 10 degrees
    h0 = hh[0] if e.get("start") else hs[0]
    h1 = hh[-1] if e.get("end") else hs[-1]
    turn = -math.degrees(h1 - h0)  # the game's convention: + turns right
    m["turn_deg"] = round(turn, 1)
    if x["turn_deg"] is not None:
        m["turn_err_deg"] = round(abs(turn - x["turn_deg"]), 1)
    if kind == "loop":
        a = min(round(e.get("skip", 1.5 if family(e) else 0) * FPS), T // 2)
        if path:
            a = max(a, min(round(path[0][0] * FPS), T // 2))
        tv = root[-1, [0, 2]] - root[a, [0, 2]]
        dist = float(np.hypot(*tv))
        m["speed_m_s"] = round(dist / ((T - 1 - a) / FPS), 3)
        face = math.atan2(np.sin(hh[a:]).mean(), np.cos(hh[a:]).mean())
        chest = headings(P, LSHO, RSHO)
        if family(e):  # a gait should hold its facing; an activity loop may turn about
            m["facing_drift_deg"] = round(math.degrees(float(np.ptp(smooth(chest[a:], FPS)))), 1)
        if x["travel_deg"] is not None and dist > 0.2:
            trav = math.atan2(tv[0], tv[1])
            m["travel_deg"] = round(-math.degrees(math.remainder(trav - face, 2 * math.pi)), 1)
            m["travel_dir_err_deg"] = round(abs(math.degrees(math.remainder(math.radians(m["travel_deg"] - x["travel_deg"]), 2 * math.pi))), 1)
        elif x["travel_deg"] is not None:
            m["travel_dir_err_deg"] = 180.0  # asked to travel, did not
        if x["speed"]:
            m["travel_err_m"] = round(abs(m["speed_m_s"] - x["speed"]) * (T - 1 - a) / FPS, 3)
            m["travel_expected_m"] = round(float(x["speed"]) * (T - 1 - a) / FPS, 3)
        fam = family(e)
        if fam and dist > 0.2:
            # the laptop's no-slide line (SPEEDS.md, 2026-11-11): the slower toe within 5 cm of the
            # floor (above its standing height, 2 cm) moves at most 5 % of the body's speed (median).
            # On the raw take this is the share at the take's own speed; the game plays a gait's
            # phase at the body's speed, so the share holds at any driven speed
            tw = np.zeros((T, 2))
            for i, j in enumerate((LTOE, RTOE)):
                tw[1:, i] = np.hypot(*(P[1:, j, [0, 2]] - P[:-1, j, [0, 2]]).T) * FPS
            slow = np.where(P[:, [LTOE, RTOE], 1] < TOE_REST_M + 0.05, tw, np.inf).min(axis=1)[max(a, 1):]
            slow = slow[np.isfinite(slow)]
            if len(slow) and m["speed_m_s"] > 0:
                m["toe_slide_pct"] = round(100 * float(np.median(slow)) / m["speed_m_s"], 1)
                m["toe_slide_p75_pct"] = round(100 * float(np.percentile(slow, 75)) / m["speed_m_s"], 1)
            m["air_share"] = round(float(air[a:].mean()), 2)  # both feet off the ground: a run's flight
            m["hips_bounce_cm"] = round(100 * float(np.ptp(root[a:, 1])), 1)  # run#1: 8, run_fast#1: 9; a bounding take: 30+
        if fam and dist > 0.2:
            # Plants and planted slide, as the game's marker_check.py measures them on the baked
            # clip (living/tools/marker_check.py, `slide`), emulated on the raw take driven at the
            # entry's `game_speed` (game m/s on Vivi; default: the take's own speed):
            # - the take is re-timed as the bake does (animate.py resample: n / time-scale frames);
            # - a foot is down in a frame while its heel point or its ball is within 3 cm (game) of
            #   the sole's standing height and moves at most 0.3 game m/s to the next frame
            #   (animate.py foot_markers), gaps of up to 2 frames filled and plants of up to 2
            #   dropped (clean_contacts(gap=2, short=2)); the heel point is under the ankle at the
            #   ball's height, a quarter of the foot behind it, rigid with the foot;
            # - over each plant, the slower of the two points' movement against the ground is
            #   summed frame by frame; the ground passes at the clip's own speed, which on the raw
            #   take is the point's movement in the take's world. The worst plant is the slide.
            # It is a total distance per plant (cm), not a share of speed. marker_check warns
            # above 4 cm; the laptop's rule (2026-11-12) is also that every plant holds 4 frames.
            nat = m["speed_m_s"] * K_GAME
            sc = float(e["game_speed"]) / nat if e.get("game_speed") and nat > 0 else 1.0
            n_ = T - 1
            mm = max(2, round(n_ / sc))
            xs = np.arange(mm + 1) * n_ / mm
            i0 = np.minimum(np.floor(xs).astype(int), n_)
            i1 = np.minimum(i0 + 1, n_)
            wt = (xs - i0)[:, None]
            lens, slides, counts = [], [], {}
            for side, ank, ball in (("L", LFOOT, LTOE), ("R", RFOOT, RTOE)):
                heel = P[:, ank] + np.einsum("tij,j->ti", d["G"][:, ank], np.array(HEEL_IN_ANKLE[side]))
                pts = [heel[i0] * (1 - wt) + heel[i1] * wt, P[i0, ball] * (1 - wt) + P[i1, ball] * wt]
                step = [np.hypot(*(q[1:, [0, 2]] - q[:-1, [0, 2]]).T) for q in pts]  # to the next frame
                dn = np.zeros(mm, bool)
                for q, st in zip(pts, step):
                    dn |= ((q[:-1, 1] - TOE_REST_M) * K_GAME <= 0.03) & (st * FPS * K_GAME <= 0.3)
                c = list(dn)
                for val, run in ((True, 2), (False, 2)):
                    i = 0
                    while i < mm:
                        if c[i] != val:
                            j = i
                            while j < mm and c[j] != val:
                                j += 1
                            if j - i <= run and i > 0 and j < mm:
                                c[i:j] = [val] * (j - i)
                            i = j
                        else:
                            i += 1
                slow = np.minimum(step[0], step[1])
                wins = [(x, y + 1) for x, y in runs(c) if x >= a / sc and y + 1 < mm]  # whole plants after the skip
                counts[side] = len(wins)
                lens += [y - x for x, y in wins]
                slides += [float(slow[x:y].sum()) * K_GAME for x, y in wins]
            m["time_scale"] = round(sc, 3)
            m["plants"] = f"L{counts['L']} R{counts['R']}"
            m["plant_frames_min"] = int(min(lens)) if lens and min(counts.values()) else 0
            m["plant_frames_med"] = round(float(np.median(lens)), 1) if lens else 0.0
            # a foot that never plants cannot be measured: 99 fails the check
            m["plant_slide_cm"] = round(100 * max(slides), 1) if slides and min(counts.values()) else 99.0
            m["plant_slide_med_cm"] = round(100 * float(np.median(slides)), 1) if slides else None
        # `cadence_ref`: the forward entry made for the same speed (a forward take names itself: its
        # period and metres a cycle are reported, not checked). Default: the family's forward gait
        ref_name = e.get("cadence_ref", fam)
        if fam and e["name"] != fam:
            u = tv / max(dist, 1e-9)
            k = period((P[a:, LFOOT, [0, 2]] - P[a:, RFOOT, [0, 2]]) @ u) if dist > 0.2 else None
            m["period_s"] = round(k / FPS, 3) if k else None
            m["cycle_m"] = round(m["speed_m_s"] * k / FPS, 3) if k else None  # metres a gait cycle
        if fam and e["name"] not in (fam, ref_name):
            ref = refs_period(ref_name, lib, dirs)
            # against the forward gait the game plays at the rules' speed (walk 2.6, run 3.9 m/s):
            # the client steps a directional take only while it steps at most 1.6x as often
            fast = refs_cycle(e.get("cadence_ref") or FAST.get(fam, fam), lib, dirs)
            if m["cycle_m"] and fast:
                m["cycle_ratio"] = round(m["cycle_m"] / fast, 3)
            m["period_ref_s"] = ref
            if ref:
                m["cadence_err"] = round(abs(k / FPS / ref - 1), 3) if k else 1.0
    elif kind == "once":
        tv = root[-1, [0, 2]] - root[0, [0, 2]]
        m["travel_xz_m"] = [round(float(tv[0]), 3), round(float(tv[1]), 3)]
        if travels(e) and not x["turn_deg"]:  # a start, stop or jump keeps facing ahead
            chest = headings(P, LSHO, RSHO)
            m["facing_drift_deg"] = round(math.degrees(float(np.abs(smooth(chest, FPS)).max())), 1)
        if x["travel"] is not None:
            ex = np.array(x["travel"])
            m["travel_err_m"] = round(float(np.hypot(*(tv - ex))), 3)
            m["travel_expected_m"] = round(float(np.hypot(*ex)), 3)
        m["wander_m"] = round(float(np.hypot(root[:, 0] - root[0, 0], root[:, 2] - root[0, 2]).max()), 3)
    return m, es


_PERIODS = {}
FAST = {"walk": "walk_brisk", "run": "run_fast"}  # the forward gait at the rules' walk and run


def refs_cycle(name, lib, dirs):
    """Metres a cycle of the library's pick of a forward gait (speed after its skip x step period)."""
    key = "cycle:" + name
    if key not in _PERIODS:
        e = next((c for c in lib["clips"] if c["name"] == name), None)
        val = None
        if e and "pick" in e:
            d = load(find(dirs, f"{name}_s{e['pick']}.npz"))
            a = round(e.get("skip", 1.5) * FPS)
            tv = d["root"][-1, [0, 2]] - d["root"][a, [0, 2]]
            dist = float(np.hypot(*tv))
            k = period((d["P"][a:, LFOOT, [0, 2]] - d["P"][a:, RFOOT, [0, 2]]) @ (tv / max(dist, 1e-9)))
            val = dist / ((len(d["P"]) - 1 - a) / FPS) * k / FPS if k else None
        _PERIODS[key] = val
    return _PERIODS[key]


def refs_period(fam, lib, dirs):
    """Step period (s) of the library's forward pick of a gait family (walk, run, sneak)."""
    if fam in _PERIODS:
        return _PERIODS[fam]
    e = next((c for c in lib["clips"] if c["name"] == fam), None)
    val = None
    if e and "pick" in e:
        d = load(find(dirs, f"{fam}_s{e['pick']}.npz"))
        a = round(e.get("skip", 1.5) * FPS)
        tv = d["root"][-1, [0, 2]] - d["root"][a, [0, 2]]
        u = tv / max(float(np.hypot(*tv)), 1e-9)
        k = period((d["P"][a:, LFOOT, [0, 2]] - d["P"][a:, RFOOT, [0, 2]]) @ u)
        val = round(k / FPS, 3) if k else None
    _PERIODS[fam] = val
    return val


def judge(e, m, expects):
    """Checks that apply to this entry: {name: {metric, value, limit, op, ratio, pass}}."""
    out = {}
    kind = e.get("kind")
    skip = set()
    if kind == "pose":
        skip |= {"active", "frozen"}
    if family(e) or (kind == "once" and e.get("plant") is False):
        skip |= {"active"}  # a gait is busy by itself; a fall ends still
    if not (e.get("hop") or e["name"].startswith("jump")):
        skip |= {"air"}
    limits = dict(LIMITS)
    asked = set()
    if family(e) or travels(e) or e.get("turn_deg") or e.get("end_yaw"):  # a turn pivots its feet
        limits["slide"] = ("slide_p90_cm_s", GAIT_SLIDE_CM_S, "max")
    limits["travel"] = ("travel_err_m", max(0.12, 0.12 * m.get("travel_expected_m", 0.0)), "max")
    for ex in expects:
        mm = re.fullmatch(r"([a-z_0-9]+)\s*(>=|<=)\s*([-0-9.]+)", ex)
        if not mm:
            raise SystemExit(f"bad --expect {ex!r}: use METRIC>=X or METRIC<=X")
        name, op, val = mm.groups()
        op = "min" if op == ">=" else "max"
        # replace a check on the same metric and side; a range (>= and <=) gets two checks
        key = next((k for k, v in limits.items() if v[0] == name and v[2] == op), None)
        if key is None:
            key = f"expect_{name}" if f"expect_{name}" not in limits else f"expect_{name}_{op}"
        limits[key] = (name, float(val), op)
        skip.discard(key)  # asked for explicitly
        asked.add(key)
    for check, (metric, limit, op) in limits.items():
        if check in skip:
            continue
        if metric not in m or m[metric] is None:
            if check in asked:  # asked for and not measured on this take: fail it, never pass it
                out[check] = {"metric": metric, "value": None, "limit": limit, "op": op, "ratio": 9.0, "pass": False}
            continue
        v = float(m[metric])
        if limit > 0 and (v >= 0 or op == "min"):  # the usual case: a share, a distance, a speed
            r = v / limit if op == "max" else (limit / v if v > 0 else 9.0)
        else:  # a signed limit (feet_gap_min_cm<=0): pass or fail, and by how much
            over = v - limit if op == "max" else limit - v
            r = 0.0 if over <= 0 else 1.0 + over / max(abs(limit), 1.0)
        out[check] = {"metric": metric, "value": m[metric], "limit": round(float(limit), 3), "op": op, "ratio": round(float(r), 2), "pass": bool(r <= 1.0 or check in SOFT)}
    return out


def pick(takes, old_pick):
    for t in takes:
        t["fails"] = [k for k, c in t["checks"].items() if not c["pass"]]
        t["penalty"] = round(sum(min(c["ratio"], 3.0) for c in t["checks"].values()), 2)
    key = lambda t: (len(t["fails"]), t["penalty"], t["source"] != "library", t["seed"])
    ranked = sorted(takes, key=key)
    w = ranked[0]
    old = next((t for t in takes if t["source"] == "library" and t["seed"] == old_pick), None)
    if w["fails"]:
        why = f"no take passes every check; s{w['seed']} fails the fewest ({', '.join(w['fails'])}) with penalty {w['penalty']}"
    else:
        n = sum(1 for t in takes if not t["fails"])
        why = f"s{w['seed']} passes every check and has the lowest penalty of {n} passing take(s): {w['penalty']}"
        if len(ranked) > 1 and not ranked[1]["fails"]:
            why += f" (next s{ranked[1]['seed']} {ranked[1]['penalty']})"
    if old:
        if old is w:
            why += "; it is the library's current pick: nothing new beat it"
        else:
            why += f"; the old pick s{old['seed']} has penalty {old['penalty']}" + (f" and fails {', '.join(old['fails'])}" if old["fails"] else "")
    return w, why, [t["seed"] for t in ranked]


# ---------------------------------------------------------------------------------------------
# Drawing


def bones(skel_path):
    skel = json.load(open(skel_path))
    idx = {j["name"]: j["index"] for j in skel["joints"]}
    out = []
    for j in skel["joints"]:
        if j["parent"] is None or j["index"] in FINGERS:
            continue
        n = j["name"]
        col = (90, 150, 255) if n.startswith("Left") else (255, 110, 90) if n.startswith("Right") else (225, 225, 225)
        out.append((idx[j["parent"]], j["index"], col))
    return out


def draw(dr, p, fc, bn, ox, gy, scale, view, centre):
    def pt(q):
        u = q[2] - centre[2] if view == "side" else -(q[0] - centre[0])
        return (ox + u * scale, gy - q[1] * scale)
    for a, b, col in sorted(bn, key=lambda b: p[b[1]][0] if view == "side" else p[b[1]][2]):
        dr.line([pt(p[a]), pt(p[b])], fill=col, width=2)
    for j in FINGERS:
        if p[j][1] < -0.01:
            x, y = pt(p[j])
            dr.ellipse([x - 2, y - 2, x + 2, y + 2], fill=(255, 60, 200))
    for col, j in CONTACT:
        if fc[col]:
            x, y = pt(p[j])
            dr.ellipse([x - 2, y - 2, x + 2, y + 2], fill=(80, 255, 120))


def take_strip(t, es, bn, n=10, w=120, h=170):
    d = load(t["file"])
    P, fc, root = d["P"], d["fc"], d["root"]
    T = len(P)
    idx = [round(i * (T - 1) / (n - 1)) for i in range(n)]
    eh = 50
    im = Image.new("RGB", (n * w, 2 * h + eh + 34), (24, 26, 30))
    dr = ImageDraw.Draw(im)
    verdict = "PASS" if not t["fails"] else "fails " + ",".join(t["fails"])
    dr.text((6, 3), f"s{t['seed']} ({t['source']}{', v' + str(t['variant']) if t['variant'] is not None else ''})  penalty {t['penalty']}  {verdict}", fill=(255, 230, 120) if t.get("winner") else (240, 240, 240))
    dr.text((6, 16), (t["prompt"] or "")[:150], fill=(160, 160, 160))
    sc = 0.45 * h
    for r, view in enumerate(("front", "side")):
        gy = 32 + (r + 1) * h - 10
        dr.line([(0, gy), (n * w, gy)], fill=(90, 90, 90))
        for c, f in enumerate(idx):
            draw(dr, P[f], fc[f], bn, c * w + w / 2, gy, sc, view, root[f])
            if r == 0:
                dr.text((c * w + 3, 34), f"{f / FPS:.2f}s", fill=(150, 150, 150))
    y0 = 32 + 2 * h + eh
    top = max(0.4, float(es.max()))
    pts = [(i * (n * w - 1) / max(T - 1, 1), y0 - es[i] / top * (eh - 4)) for i in range(T)]
    dr.line([(0, y0 - ACTIVE_M_S / top * (eh - 4)), (n * w, y0 - ACTIVE_M_S / top * (eh - 4))], fill=(120, 80, 80))
    dr.line(pts, fill=(120, 220, 255), width=2)
    dr.text((4, y0 - eh + 2), f"energy (active {t['metrics']['active_share']}, frozen {t['metrics']['frozen_s']} s)", fill=(150, 150, 150))
    return im


def stack(ims):
    out = Image.new("RGB", (max(i.width for i in ims), sum(i.height for i in ims)), (0, 0, 0))
    y = 0
    for i in ims:
        out.paste(i, (0, y))
        y += i.height
    return out


# ---------------------------------------------------------------------------------------------
# Generation


def others_generating():
    """Running Kimodo batches: python processes whose script is a batch.py (any checkout's)."""
    out = []
    for pid in filter(str.isdigit, os.listdir("/proc")):
        try:
            argv = open(f"/proc/{pid}/cmdline", "rb").read().split(b"\0")
        except OSError:
            continue
        if len(argv) > 1 and os.path.basename(argv[0]).startswith(b"python") and argv[1].endswith(b"batch.py"):
            out.append(f"{pid} " + b" ".join(argv[1:3]).decode(errors="replace"))
    return out


def mem_available_gb():
    for l in open("/proc/meminfo"):
        if l.startswith("MemAvailable:"):
            return int(l.split()[1]) / 2**20
    return 0.0


def wait_for_gpu(need_gb, wait):
    t0 = time.time()
    while True:
        busy, avail = others_generating(), mem_available_gb()
        if not busy and avail - need_gb >= 40:
            return
        if not wait:
            raise SystemExit(f"GPU busy or RAM short: {busy[:2]}, {avail:.0f} GB available")
        if time.time() - t0 < 1 or int(time.time() - t0) % 300 < 30:
            print(f"waiting: {len(busy)} other batch.py, {avail:.0f} GB available", flush=True)
        time.sleep(30)


def generate(variants, lib, refs, takes_dir, batch, wait):
    os.makedirs(takes_dir, exist_ok=True)
    for v in variants:
        for spec in (v["entry"].get("start"), v["entry"].get("end"), "neutral"):
            if not spec:
                continue
            spec = lib["neutral"] if spec == "neutral" else spec
            name, seed = spec.split("@")[0].split("#")
            fname = f"{name}_s{int(seed)}.npz"
            dst = os.path.join(takes_dir, fname)
            if os.path.lexists(dst) and not os.path.exists(dst):
                os.remove(dst)  # a stale link
            if not os.path.lexists(dst):
                os.symlink(os.path.abspath(find(refs, fname)), dst)
    todo = [v for v in variants if any(not os.path.exists(os.path.join(takes_dir, f"{v['entry']['name']}_s{s}.npz")) for s in v["entry"]["seeds"])]
    if not todo:
        return
    cfg = os.path.join(takes_dir, f"lab-{int(time.time())}.json")
    json.dump({"steps": lib.get("steps", 100), "cfg": lib.get("cfg", [2.0, 2.0]), "neutral": lib["neutral"],
               "clips": [v["entry"] for v in todo]}, open(cfg, "w"), indent=1)
    lock = open(LOCK, "a")
    while True:  # one cliplab generation at a time on this machine, then the /proc and RAM checks
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except BlockingIOError:
            if not wait:
                raise SystemExit(f"another cliplab holds {LOCK}")
            time.sleep(30)
    wait_for_gpu(20, wait)
    env = dict(os.environ, TEXT_ENCODER_MODE="local", HF_HUB_OFFLINE="1")
    cmd = ["nice", "-n", "10", VENV_PY, batch, cfg, takes_dir]
    print("GENERATE", " ".join(cmd), flush=True)
    with open(os.path.join(takes_dir, "batch.log"), "a") as log:
        p = subprocess.Popen(cmd, cwd=os.path.dirname(batch), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for line in p.stdout:
            log.write(line)
            if line.startswith(("LOAD", "GEN", "{")) or "Error" in line:
                print("  " + line.rstrip()[:200], flush=True)
        if p.wait():
            raise SystemExit(f"batch.py failed ({p.returncode}); see {takes_dir}/batch.log")


# ---------------------------------------------------------------------------------------------
# clips.json


def set_entry(clips_path, entry):
    """Replace the one-line entry of the same name in clips.json (or append it), keeping the layout."""
    src = open(clips_path).read().split("\n")
    head = json.dumps({"name": entry["name"]})[:-1] + ","
    line = "    " + json.dumps(entry)
    hits = [i for i, l in enumerate(src) if l.lstrip().startswith(head)]
    if hits:
        i = hits[0]
        src[i] = line + ("," if src[i].rstrip().endswith(",") else "")
    else:
        end = max(i for i, l in enumerate(src) if l.strip() == "]")
        j = end - 1
        while not src[j].strip():
            j -= 1
        src[j] = src[j].rstrip().rstrip(",") + ","
        src.insert(j + 1, line)
    open(clips_path, "w").write("\n".join(src))
    json.load(open(clips_path))


def parse_set(items):
    out = {}
    for s in items:
        k, v = s.split("=", 1)
        out[k] = json.loads(v)
    return out


def check_entry(e, batch):
    """Refuse before any GPU wait: an entry batch.py cannot run, or keys the chosen batch.py ignores."""
    if not e.get("seconds") or e["seconds"] <= 0:
        raise SystemExit(f"{e['name']}: no seconds; give --seconds")
    if "heading" in e and not e.get("path"):
        raise SystemExit(f"{e['name']}: heading needs a path")
    src = open(batch).read()
    missing = [k for k in ("heading", "end_yaw") if k in e and f'"{k}"' not in src]
    if missing:
        raise SystemExit(f"{e['name']} uses {missing}, which {batch} does not support: pass --batch with a batch.py that does "
                         "(the assets-locomotion branch's)")


def variants_for(e, a, used):
    """New variants (one per --prompt, or the entry's prompt) with fresh seed blocks above `used`."""
    prompts = a.prompt or [e.get("prompt")]
    if not prompts[0]:
        raise SystemExit(f"{e['name']} has no prompt; give --prompt")
    block = 10 * math.ceil(a.seeds / 10)
    base = a.seed_base if a.seed_base is not None else block * (max(used, default=-1) // block + 1)
    clash = used & set(range(base, base + block * len(prompts)))
    if clash:
        raise SystemExit(f"--seed-base {base}: seeds {sorted(clash)} of {e['name']} are already used")
    out = []
    for i, pr in enumerate(prompts):
        v = dict(e)
        v["prompt"] = pr
        v["seeds"] = list(range(base + i * block, base + i * block + a.seeds))
        v.pop("pick", None)
        out.append({"variant": i, "entry": v})
    return out


def seeds_used(name, dirs):
    pat = re.compile(re.escape(name) + r"_s(\d+)\.npz$")
    return {int(m.group(1)) for d in dirs if os.path.isdir(d) for f in os.listdir(d) for m in [pat.match(f)] if m}


# ---------------------------------------------------------------------------------------------


def summary(m, checks):
    keys = ["active", "frozen", "floor_hands", "floor_fingers", "floor_feet", "floor_body", "slide", "drift", "plant_slide", "loop_pose", "loop_vel",
            "start_key", "end_key", "path", "travel", "travel_dir", "turn", "facing", "cadence", "air", "hop", "pop"]
    bits = []
    for k in keys + [k for k in checks if k.startswith("expect_")]:
        if k in checks:
            c = checks[k]
            bits.append(f"{k} {c['value']}{'' if c['pass'] else '!'}")
    bits.append(f"steps {m['step_feet'] or 0}")
    return " · ".join(bits)


def lab(name, a, lib, clips_path):
    e0 = next((c for c in lib["clips"] if c["name"] == name), None)
    if e0 is None and not a.prompt and not os.path.exists(os.path.join(a.out, name, "variants.json")):
        raise SystemExit(f"{name} is not in {clips_path}; give --prompt and the entry fields with --set")
    e0 = dict(e0 or {"name": name, "kind": "once", "seeds": []})
    e = dict(e0)
    e.update(parse_set(a.set))
    e = {k: v for k, v in e.items() if v is not None}
    if a.seconds:
        e["seconds"] = a.seconds
    out = os.path.join(a.out, name)
    takes_dir = os.path.join(out, "takes")
    dirs = [a.lib] + a.takes + [takes_dir]
    refs = [a.lib, takes_dir] + a.takes
    os.makedirs(out, exist_ok=True)
    state_path = os.path.join(out, "variants.json")
    variants = json.load(open(state_path)) if os.path.exists(state_path) else []
    if a.write:
        return adopt(json.load(open(os.path.join(out, "checks.json"))), a, clips_path, lib)
    if not a.score_only:
        check_entry(e, a.batch)
        with open(os.path.join(out, ".lock"), "a") as clip_lock:
            fcntl.flock(clip_lock, fcntl.LOCK_EX)  # one run per clip: seeds and variants.json
            variants = json.load(open(state_path)) if os.path.exists(state_path) else []
            new = variants_for(e, a, seeds_used(name, dirs) | {s for v in variants for s in v["entry"]["seeds"]})
            for i, v in enumerate(new):
                v["variant"] = len(variants) + i
            variants += new
            json.dump(variants, open(state_path, "w"), indent=1)  # before generating: a failed batch keeps what it made
            generate(new, lib, refs, takes_dir, a.batch, not a.no_wait)

    takes = []
    for s in e0.get("seeds", []):
        f = os.path.join(a.lib, f"{name}_s{s}.npz")
        if not os.path.exists(f) and a.takes:
            f = next((os.path.join(d, f"{name}_s{s}.npz") for d in a.takes if os.path.exists(os.path.join(d, f"{name}_s{s}.npz"))), f)
        if os.path.exists(f):
            takes.append({"seed": s, "source": "library", "variant": None, "prompt": e0.get("prompt"), "file": f, "entry": e0})
    for v in variants:
        for s in v["entry"]["seeds"]:
            f = os.path.join(takes_dir, f"{name}_s{s}.npz")
            if os.path.exists(f) and not any(t["seed"] == s for t in takes):
                takes.append({"seed": s, "source": "lab", "variant": v["variant"], "prompt": v["entry"]["prompt"], "file": f, "entry": v["entry"]})
    if not takes:
        raise SystemExit(f"no takes of {name} found")
    curves = {}
    for t in takes:
        # scored against the entry as the lab asks for it (`--set` changes apply to old takes too)
        se = dict(e)
        se["prompt"] = t["prompt"]
        m, es = measure(se, t["file"], lib, dirs, refs)
        t["metrics"], t["checks"] = m, judge(se, m, a.expect)
        curves[t["seed"]] = es
    w, why, order = pick(takes, e0.get("pick"))
    warnings = lint(e, takes[0]["metrics"]["frames"])
    w["winner"] = True
    # the entry to write: the one the winner was judged against, with the prompt and seeds that made it
    chosen = dict(e)
    chosen["prompt"], chosen["seeds"] = w["entry"].get("prompt"), list(w["entry"]["seeds"])
    chosen["pick"] = w["seed"]
    same = lambda x, y: {k: v for k, v in x.items() if k not in ("prompt", "seeds", "pick", "note")} == \
        {k: v for k, v in y.items() if k not in ("prompt", "seeds", "pick", "note")}
    if not same(w["entry"], e):
        warnings_gen = ["the winner was generated from an entry that differs from the one it was judged against "
                        "(a --set changed between runs); --write refuses it"]
    else:
        warnings_gen = []
    report = {
        "clip": name, "date": datetime.date.today().isoformat(), "clips_json": clips_path, "entry_before": e0,
        "entry_scored": e, "entry_chosen": chosen, "expect": a.expect, "entry_warnings": warnings + warnings_gen,
        "out": a.out,
        "limits": {k: list(v) for k, v in LIMITS.items()}, "active_m_s": ACTIVE_M_S, "still_m_s": STILL_M_S,
        "pick_rule": "eligible = fails no check; lowest penalty = sum of min(ratio, 3) over checks; ties: library take, then lower seed; none eligible: fewest fails, then penalty",
        "winner": {"seed": w["seed"], "source": w["source"], "variant": w["variant"], "prompt": w["prompt"], "why": why},
        "ranking": order,
        "variants": [{"variant": v["variant"], "prompt": v["entry"]["prompt"], "seeds": v["entry"]["seeds"]} for v in variants],
        "takes": [{k: t[k] for k in ("seed", "source", "variant", "prompt", "file", "penalty", "fails", "metrics", "checks")} for t in takes],
    }
    json.dump(report, open(os.path.join(out, "checks.json"), "w"), indent=1)
    bn = bones(os.path.join(HERE, "somaskel77_skeleton.json"))
    ranked = sorted(takes, key=lambda t: order.index(t["seed"]))
    stack([take_strip(t, curves[t["seed"]], bn) for t in ranked]).save(os.path.join(out, "sheet.png"))
    take_strip(w, curves[w["seed"]], bn).save(os.path.join(out, "pick.png"))
    old = next((t for t in takes if t["source"] == "library" and t["seed"] == e0.get("pick")), None)
    line = (f"| {name} | s{w['seed']} ({w['source']}{', v' + str(w['variant']) if w['variant'] is not None else ''}) | "
            f"{'pass' if not w['fails'] else 'FAIL ' + ','.join(w['fails'])} | {summary(w['metrics'], w['checks'])} | "
            + (f"old s{old['seed']}: {'pass' if not old['fails'] else 'fails ' + ','.join(old['fails'])}, penalty {old['penalty']}" if old and old is not w else "old pick kept" if old else "new")
            + f" | {len(takes)} takes |")
    with open(os.path.join(a.out, "report.md"), "a") as f:
        f.write(line + "\n")
    print(line)
    print("  " + why)
    for wn in warnings:
        print("  ENTRY: " + wn)
    if a.verbose:
        for t in ranked:
            print(f"   s{t['seed']:<3} {t['source']:<7} pen {t['penalty']:<5} {'pass' if not t['fails'] else 'fails ' + ','.join(t['fails'])}  {summary(t['metrics'], t['checks'])}")
    return report


def dependents(lib, name, keep_seeds, same_prompt):
    """Entries (and the library's neutral) keyed to a take of `name` that the new entry would no longer make."""
    out = []
    specs = [("neutral", lib.get("neutral"))] + [(c["name"], c.get(k)) for c in lib["clips"] for k in ("start", "end")]
    for who, spec in specs:
        if spec and spec != "neutral" and spec.split("#")[0] == name:
            seed = int(spec.split("#")[1].split("@")[0])
            if seed not in keep_seeds or not same_prompt:
                out.append(f"{who} ({spec})")
    return out


def adopt(report, a, clips_path, lib):
    """Adopt the last run's winner (`<out>/<clip>/checks.json`, as scored): copy its variant's takes
    into the library (never overwriting) and set its entry in clips.json."""
    w, name = report["winner"], report["clip"]
    entry = dict(report["entry_chosen"])
    if a.take is not None and a.take != w["seed"]:
        # a take chosen by a person (a verdict), not the lab's winner: its own variant's entry
        t = next((t for t in report["takes"] if t["seed"] == a.take), None)
        if t is None:
            raise SystemExit(f"{name}: s{a.take} was not scored in {report['out']}/{name}/checks.json")
        strip = lambda x: {k: v for k, v in x.items() if k not in ("prompt", "seeds", "pick", "note")}
        if t["source"] == "lab":
            made = next(v["entry"] for v in json.load(open(os.path.join(report.get("out", a.out), name, "variants.json")))
                        if v["variant"] == t["variant"])
        else:
            made = report["entry_before"]
        if strip(made) != strip(report["entry_scored"]):
            raise SystemExit(f"{name}: s{a.take} was generated from an entry that differs from the one it was judged against")
        entry = dict(report["entry_scored"])
        entry["prompt"], entry["seeds"], entry["pick"] = made["prompt"], list(made["seeds"]), a.take
        w = {"seed": a.take, "source": t["source"],
             "why": f"chosen with --take over the lab's s{w['seed']}; it " + ("passes every check" if not t["fails"] else "fails " + ", ".join(t["fails"]))}
    elif any("--write refuses" in x for x in report.get("entry_warnings", [])):
        raise SystemExit(f"{name}: " + "; ".join(report["entry_warnings"]))
    if a.note:
        entry["note"] = a.note
    before = report["entry_before"]
    deps = dependents(lib, name, set(entry["seeds"]), entry.get("prompt") == before.get("prompt"))
    if deps and not a.rekey:
        raise SystemExit(f"{name}: {', '.join(deps)} start or end in a take this entry would no longer make; "
                         "re-key them (and re-run them) and pass --rekey")
    if w["source"] == "lab":
        src_dir = os.path.join(report.get("out", a.out), name, "takes")
        pairs = [(os.path.join(src_dir, f"{name}_s{s}.npz"), os.path.join(a.lib, f"{name}_s{s}.npz")) for s in entry["seeds"]]
        for src, dst in pairs:  # check everything before copying anything
            if os.path.exists(dst) and os.path.exists(src) and open(src, "rb").read() != open(dst, "rb").read():
                raise SystemExit(f"{dst} exists and differs: not overwriting")
        for src, dst in pairs:
            if os.path.exists(src) and not os.path.exists(dst):
                shutil.copy2(src, dst)
                print(f"  library + {os.path.basename(dst)}")
    set_entry(clips_path, entry)
    print(f"  {clips_path}: {name} pick {entry['pick']} (s{w['seed']}, {w['source']}: {w['why']})")
    for d in deps:
        print(f"  re-key: {d}")


def handoff(group, names, a, clips_path, lib):
    """Tarball for the laptop: chosen raw takes under library/, entries, checks.json per clip.
    `--changed` names the clips whose pick the lab chose (its winner); the others keep their pick."""
    changed = set(names) if a.changed is None else {n for n in a.changed.split(",") if n}
    date = datetime.date.today().isoformat()
    os.makedirs(a.handoff_dir, exist_ok=True)
    path = os.path.join(a.handoff_dir, f"{group}-{date}.tar.gz")
    strip = lambda x: {k: v for k, v in x.items() if k not in ("prompt", "seeds", "pick", "note")}
    rows, entries, items = [], [], []
    for name in names:  # check everything before writing anything
        e = next((c for c in lib["clips"] if c["name"] == name), None)
        if e is None:
            raise SystemExit(f"{name} is not in {clips_path}")
        ck = os.path.join(a.out, name, "checks.json")
        if not os.path.exists(ck):
            raise SystemExit(f"{name}: no {ck}; score it first")
        rep = json.load(open(ck))
        if os.path.abspath(rep["clips_json"]) != os.path.abspath(clips_path):
            raise SystemExit(f"{name}: {ck} was scored against {rep['clips_json']}, not {clips_path}; re-score")
        if any("--write refuses" in x for x in rep.get("entry_warnings", [])):
            raise SystemExit(f"{name}: " + "; ".join(rep["entry_warnings"]))
        if strip(rep["entry_scored"]) != strip(e):
            raise SystemExit(f"{name}: its entry differs from the one {ck} judged; re-score it as it is")
        w = next((t for t in rep["takes"] if t["seed"] == e.get("pick")), None)
        if w is None:
            raise SystemExit(f"{name}: its pick s{e.get('pick')} was not scored; re-score it")
        lib_file = os.path.join(a.lib, f"{name}_s{e['pick']}.npz")
        if os.path.exists(lib_file) and open(lib_file, "rb").read() != open(w["file"], "rb").read():
            raise SystemExit(f"{name}: the scored take {w['file']} differs from {lib_file}")
        entries.append(e)
        items.append((name, e, ck, w))
        other = f" (lab ranks s{rep['winner']['seed']} first)" if rep["winner"]["seed"] != e["pick"] else ""
        change = ("retake" + (" by verdict" + other if other else "")) if name in changed else "kept" + other
        rows.append(f"| {name} | s{e['pick']} | {change} | {'pass' if not w['fails'] else 'FAIL ' + ','.join(w['fails'])} | {w['penalty']} | {summary(w['metrics'], w['checks'])} |")
    table = "| clip | pick | change | verdict | penalty | scores |\n|---|---|---|---|---|---|\n" + "\n".join(rows) + "\n"
    tmp = path + ".tmp"
    with tarfile.open(tmp, "w:gz") as tar:
        def add_bytes(arc, data):
            ti = tarfile.TarInfo(arc)
            ti.size, ti.mtime = len(data), int(time.time())
            tar.addfile(ti, io.BytesIO(data))
        for name, e, ck, w in items:
            tar.add(w["file"], arcname=f"library/{name}_s{e['pick']}.npz")
            tar.add(ck, arcname=f"checks/{name}.json")
            for img in ("pick.png", "sheet.png"):
                if os.path.exists(os.path.join(a.out, name, img)):
                    tar.add(os.path.join(a.out, name, img), arcname=f"sheets/{name}_{img}")
        for x in a.extra:  # notes and evidence beside the takes (e.g. the scores of takes set aside)
            src, _, arc = x.partition("=")
            tar.add(src, arcname="extra/" + (arc or os.path.basename(src)))
        add_bytes("clips_entries.json", ("[\n" + ",\n".join("  " + json.dumps(x) for x in entries) + "\n]\n").encode())
        add_bytes("scores.md", table.encode())
    sha = hashlib.sha256(open(tmp, "rb").read()).hexdigest()
    os.replace(tmp, path)
    open(path + ".sha256.tmp", "w").write(f"{sha}  {os.path.basename(path)}\n")
    os.replace(path + ".sha256.tmp", path + ".sha256")
    print(path)
    print(sha)
    print(table)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--clip", required=True, help="comma-separated entry names")
    ap.add_argument("--prompt", action="append", default=[], help="a prompt variant (repeatable)")
    ap.add_argument("--seconds", type=float)
    ap.add_argument("--seeds", type=int, default=8, help="new takes per variant")
    ap.add_argument("--seed-base", type=int)
    ap.add_argument("--set", action="append", default=[], help="KEY=JSON entry override (null removes)")
    ap.add_argument("--expect", action="append", default=[], help="extra check, METRIC>=X or METRIC<=X")
    ap.add_argument("--score-only", action="store_true", help="score the existing takes; generate nothing")
    ap.add_argument("--write", action="store_true", help="adopt the last run's winner (its checks.json): copy its takes into --lib, set its entry in --clips")
    ap.add_argument("--note", help="with --write: the entry's new note")
    ap.add_argument("--take", type=int, help="with --write: adopt this scored seed instead of the winner (a verdict)")
    ap.add_argument("--rekey", action="store_true", help="with --write: adopt although other entries are keyed to a take it drops")
    ap.add_argument("--handoff", metavar="GROUP", help="write ~/clip-handoff/GROUP-<date>.tar.gz for --clip")
    ap.add_argument("--handoff-dir", default=os.path.expanduser("~/clip-handoff"))
    ap.add_argument("--extra", action="append", default=[], metavar="FILE[=NAME]", help="with --handoff: a file to add under extra/ (repeatable)")
    ap.add_argument("--changed", help="with --handoff: the clips retaken (default: all); the rest keep their pick")
    ap.add_argument("--clips", default=os.path.join(REPO, "living/tools/blender/clips.json"))
    ap.add_argument("--lib", default=DEFAULT_LIB, help="the raw library (read; --write adds files)")
    ap.add_argument("--takes", action="append", default=[], help="more directories to look for takes and poses in")
    ap.add_argument("--out", default=os.path.expanduser("~/cliplab"))
    ap.add_argument("--batch", default=os.path.join(HERE, "batch.py"))
    ap.add_argument("--no-wait", action="store_true", help="fail instead of waiting for the GPU")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()
    a.out, a.lib, a.batch, a.handoff_dir = (os.path.abspath(x) for x in (a.out, a.lib, a.batch, a.handoff_dir))
    a.takes = [os.path.abspath(x) for x in a.takes]
    lib = json.load(open(a.clips))
    names = [n for n in a.clip.split(",") if n]
    if a.handoff:
        handoff(a.handoff, names, a, a.clips, lib)
        return
    if a.prompt and len(names) > 1:
        raise SystemExit("--prompt applies to one clip")
    for n in names:
        lab(n, a, lib, a.clips)
        lib = json.load(open(a.clips))


if __name__ == "__main__":
    main()
