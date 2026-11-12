#!/usr/bin/env python3
"""Numbers for docs/STAMINA_PROPOSAL.md, from the laws as written (no world is run).

Today's values are copied from living/scripts/skills.rhai (rates, move_speed, motion,
combat_cost) and living/seeds/worlds/cullet/laws.rhai (rates, move_speed, tired_below);
the proposal's from the doc. Run: python3 living/tools/stamina_numbers.py
"""
import math

# ---- today -------------------------------------------------------------------------------
WALK, RUN_SHARE, FLEE_SHARE, ROAD = 2.6, 1.5, 1.15, 1.4
WOLF_WALK = 3.4
COST = dict(strike=2.0, bowshot=1.5, firebolt=12.0, heal=15.0, dodge=4.0, block=1.0, jump=2.0)
SPAWN = 85.0
# Real minutes per game hour: island 12-minute day, Cullet 48-minute day.
GH = dict(island=0.5, cullet=2.0)
# Person energy per game hour (island: shipped rate x person_pace 0.3; Cullet: its own).
PACE = 0.3
E = dict(
    island=dict(awake=-1.5 * PACE, rest=3.0 * PACE, sleep_roof=13.0 * PACE, sleep_rough=8.0 * PACE, block=-6.0 * PACE),
    cullet=dict(awake=-2.5, rest=2.5, sleep_roof=5.0, sleep_rough=2.5, block=-7.2),
)


def per_min(world, k):
    return E[world][k] / GH[world]


def speed_today(world, energy, run=False, road=False):
    s = WALK
    if world == "cullet" and 10.0 <= energy < 35.0:
        s *= 0.8
    if energy < 10.0:
        s *= 0.6
    if run:
        s *= RUN_SHARE
    if road:
        s *= ROAD
    return s


def line(t):
    print(t)


line("== today: energy in real time (per real minute) ==")
for w in ("island", "cullet"):
    r = {k: round(per_min(w, k), 2) for k in E[w]}
    line(f"{w}: {r}")
    awake = -per_min(w, "awake")
    line(f"  from spawn {SPAWN:.0f}: idle to <35 in {(SPAWN - 35) / awake:.0f} min, to <10 in {(SPAWN - 10) / awake:.0f} min")
    line(f"  an 8 s rest gives {per_min(w, 'rest') * 8 / 60:.2f}; one dodge (4) back by resting {4 / per_min(w, 'rest'):.1f} min,"
         f" by sleeping under a roof {4 / per_min(w, 'sleep_roof') * 60:.0f} s")
    line(f"  awake minutes one skill use costs: " + ", ".join(f"{k} {v / awake:.1f}" for k, v in COST.items()))
    line(f"  a 4 s guard: {COST['block'] + -per_min(w, 'block') * 4 / 60:.2f} energy")

line("\n== a play-test-like hour on the island (spawn 85) ==")
# play-test 3 shape: ten dodges and jumps (say 5 + 5), then a fight: 3 fire bolts, 1 heal, 12 strikes, 4 s guard x3
spent = 5 * 4 + 5 * 2 + 3 * 12 + 15 + 12 * 2 + 3 * (1 + 0.06 * 4)
for mins in (10, 20, 30):
    e = max(0.0, SPAWN - spent + per_min("island", "awake") * mins)
    line(f"  after {mins} min with {spent:.0f} spent on skills: energy {e:.0f} -> walk {speed_today('island', e):.2f} m/s, run {speed_today('island', e, True):.2f}")

line("\n== today's speeds (m/s) ==")
for w in ("island", "cullet"):
    for e in (85, 30, 5):
        line(f"  {w} energy {e}: walk {speed_today(w, e):.2f} run {speed_today(w, e, True):.2f}  road walk {speed_today(w, e, road=True):.2f} road run {speed_today(w, e, True, True):.2f}")
bend = math.cos(math.radians(30))
line(f"  look bend at its 30 deg limit: speed along the keys x{bend:.3f} (walk {WALK * bend:.2f}, run {WALK * RUN_SHARE * bend:.2f});"
     f" sideways drift {math.sin(math.radians(30)):.2f} of speed")

# ---- proposal ------------------------------------------------------------------------------
P = dict(run_share=1.85, st_max=100.0, st_regen=25.0, st_delay=1.0, run_drain=4.0, resume=30.0)
RUN_P = WALK * P["run_share"]


TOP = 5.5  # proposed ceiling on a run (m/s): the road's bonus stops here


def hold_run(dist, st=100.0, dt=0.01, walk=WALK, run=None):
    """Seconds to cover `dist` holding run: run while stamina lasts, walk (regenerating after the
    delay) until it is back to `resume`, run again. Off-road, no turns."""
    run = RUN_P if run is None else run
    t = x = 0.0
    running, since = True, 0.0
    while x < dist:
        if running and st <= 0.0:
            running, since = False, 0.0
        if not running and st >= P["resume"]:
            running = True
        if running:
            x += run * dt
            st -= P["run_drain"] * dt
        else:
            x += walk * dt
            since += dt
            if since >= P["st_delay"]:
                st = min(P["st_max"], st + P["st_regen"] * dt)
        t += dt
    return t


line(f"\n== proposal: walk {WALK}, run {RUN_P:.2f} (x{P['run_share']}), stamina {P['st_max']:.0f}, run {P['run_drain']}/s, regen {P['st_regen']}/s after {P['st_delay']} s ==")
line(f"  a full bar runs {P['st_max'] / P['run_drain']:.0f} s = {P['st_max'] / P['run_drain'] * RUN_P:.0f} m; empty to full in {P['st_delay'] + P['st_max'] / P['st_regen']:.1f} s")
far = 2000.0
line(f"  holding run for {far:.0f} m averages {far / hold_run(far):.2f} m/s")
places = [
    ("Cullet's square, 30 m", 30), ("its diagonal, 33 m", 33.0), ("Brackenford's square, ~60 m", 60),
    ("Cullet quay end to end, 150 m", 150), ("Fish Steps to the Crown bench, 227 m", 227),
    ("Fish Steps to the Wrack Strand's end, 315 m", 315), ("Fish Steps to the Lintel, 612 m", 612),
]
line("  | Crossing | walk today = proposed | run today | hold run, proposed | on Road: walk today = proposed | run today | hold run, proposed |")
rw, rr = WALK * ROAD, min(RUN_P * ROAD, TOP)
for name, d in places:
    line(f"  | {name} | {d / WALK:.0f} s | {d / (WALK * RUN_SHARE):.0f} s | {hold_run(d):.0f} s | {d / rw:.0f} s | {d / (rw * RUN_SHARE):.0f} s | {hold_run(d, walk=rw, run=rr):.0f} s |")
line(f"  on Road: walk {rw:.2f}, run today {WALK * RUN_SHARE * ROAD:.2f}, proposed run {rr:.2f} (capped at {TOP}); holding run {far / hold_run(far, walk=rw, run=rr):.2f} m/s on average")

line("\n== chases (straight line, gap 5 m, a catch at reach 1.4 + lunge 1.8 = 3.2 m) ==")
def chase(v_prey, v_wolf, gap=5.0, reach=3.2):
    if v_wolf <= v_prey:
        return None
    return (gap - reach) / (v_wolf - v_prey)
WOLF_RUN = WOLF_WALK * 1.5
for name, vp, vw in [("today: player runs, wolf closes at walk", WALK * RUN_SHARE, WOLF_WALK),
                     ("today: resident flees (x1.15), wolf walks", WALK * FLEE_SHARE, WOLF_WALK),
                     ("proposed: player runs 4.81, wolf runs 5.1", RUN_P, WOLF_RUN),
                     ("proposed: resident flees at run 4.81, wolf runs 5.1", RUN_P, WOLF_RUN),
                     ("proposed: both out of stamina (walk 2.6 vs 3.4)", WALK, WOLF_WALK)]:
    c = chase(vp, vw)
    line(f"  {name}: " + ("never caught" if c is None else f"caught in {c:.1f} s"))
line(f"  proposed, both full: the wolf's 20 s of run gains {(WOLF_RUN - RUN_P) * 20:.1f} m; a 5 m gap is closed to reach in {(5 - 3.2) / (WOLF_RUN - RUN_P):.1f} s")
