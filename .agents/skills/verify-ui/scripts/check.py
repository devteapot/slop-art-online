#!/usr/bin/env python3
"""Run verify-ui scenarios on a verify-ui-* world and check what they did.

  check.py --run RUN [SCENARIO ...]      scenarios: field windows talk items themes pick turns support (default: all but support)
  LIVING_GAME_THEME=night check.py …     the same in a theme (evidence in <scenario>-<theme>/)

Each scenario drives the real client headless through drive.py (one client run per scenario),
then checks the game UI's dumps (`dump:` steps: open windows, anchors, rectangles, the box and
whom it addresses, the weapon), the client log (what was sent through the player reducers) and,
for items, the authority's rows (owner SQL through verify.py). It prints PASS or FAIL per check
and writes `.local/living/verify/RUN/ui/checks.json`. Exit 1 when any check fails.

Two residents are placed beside the player and held still for the talk and items scenarios
(admin `place_at` and `set_behavior`: scene setup, not player acts).
"""
import argparse, json, math, os, re, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "../../../.."))
V = os.path.join(ROOT, ".agents/skills/verify/scripts/verify.py")
W, H = 1600, 900


def sql(run, q):
    r = subprocess.run([sys.executable, V, "sql", "--run", run, q], capture_output=True, text=True)
    t = r.stdout
    i = t.find("[")
    return json.loads(t[i:]) if i >= 0 else []


def residents(run, n=2):
    """Adults the scene can place beside the player: alive people with a mind, not players."""
    rows = sql(run, "SELECT id, name, stage, alive, kind FROM character WHERE kind = 'person'")
    rows = [r for r in rows if r.get("alive") and r.get("stage") == 2 and r.get("name") not in ("Verifier",)]
    rows.sort(key=lambda r: r["id"])
    return [r["id"] for r in rows[:n]]


THEME = os.environ.get("LIVING_GAME_THEME", "")


def drive(run, name, plan, places=(), syncs=(), extra=()):
    # A run per theme keeps its own evidence (`LIVING_GAME_THEME=night check.py …`).
    name = f"{name}-{THEME}" if THEME else name
    cmd = [sys.executable, os.path.join(HERE, "drive.py"), "--run", run, "--name", name, "--plan", plan, "--timeout", "420"]
    for p in places:
        cmd += ["--place", p]
    for s in syncs:
        cmd += ["--sync", s]
    cmd += list(extra)
    r = subprocess.run(cmd, capture_output=True, text=True)
    out = os.path.join(ROOT, ".local/living/verify", run, "ui", name)
    return out, r.returncode, r.stdout + r.stderr


def dump(out, name):
    p = os.path.join(out, f"{name}.json")
    return json.load(open(p)) if os.path.exists(p) else None


def log(out):
    p = os.path.join(out, "client.log")
    return re.sub(r"\x1b\[[0-9;]*m", "", open(p, errors="replace").read()) if os.path.exists(p) else ""


class Checks:
    def __init__(self):
        self.rows = []

    def check(self, scenario, what, ok, detail=""):
        self.rows.append({"scenario": scenario, "check": what, "ok": bool(ok), "detail": detail})
        print(f"{'PASS' if ok else 'FAIL'}  {scenario}: {what}{('  (' + detail + ')') if detail and not ok else ''}", flush=True)


def wins(d):
    return [(w["win"], w["anchor"]) for w in (d or {}).get("windows", [])]


def inside(d):
    """Every open window fits the 1600x900 picture."""
    for w in (d or {}).get("windows", []):
        r = w.get("rect") or {}
        if r.get("x", 0) < -1 or r.get("y", 0) < -1 or r.get("x", 0) + r.get("w", 0) > W + 1 or r.get("y", 0) + r.get("h", 0) > H + 1:
            return False
    return True


def apart(d):
    """No two open windows overlap."""
    rs = [w.get("rect") for w in (d or {}).get("windows", []) if w.get("rect")]
    for i, a in enumerate(rs):
        for b in rs[i + 1:]:
            if a["x"] < b["x"] + b["w"] and b["x"] < a["x"] + a["w"] and a["y"] < b["y"] + b["h"] and b["y"] < a["y"] + a["h"]:
                return False
    return True


def windows(run, c):
    s = "windows"
    plan = ("ready;wait:2;shot:01_explore;dump:01;click:@menu;wait:0.4;shot:02_menu;dump:02;click:@menu:Settings;wait:0.5;shot:03_settings;dump:03;"
            "key:KeyI:tap;wait:0.4;key:KeyL:tap;wait:0.5;shot:04_log_pack;dump:04;slide:@win:Log:head>0.62,0.45:0.6;wait:0.2;shot:05_dragging;"
            "wait:0.5;shot:06_swapped;dump:06;click:@win:Pack:close;wait:0.4;dump:07;key:KeyI:tap;wait:0.4;dump:08;key:Escape:tap;wait:0.3;dump:09;key:Escape:tap;wait:0.3;dump:10;"
            "key:Escape:tap;wait:0.4;shot:11_esc_menu;dump:11;key:Escape:tap;wait:0.3;dump:12;quit")
    out, code, text = drive(run, s, plan)
    c.check(s, "client ran and joined", code == 0, text[-300:])
    d = {k: dump(out, k) for k in ["01", "02", "03", "04", "06", "07", "08", "09", "10", "11", "12"]}
    c.check(s, "nothing open on arrival", d["01"] and wins(d["01"]) == [] and not d["01"]["menu"], str(wins(d["01"])))
    c.check(s, "Menu button opens the Menu list", d["02"] and d["02"]["menu"])
    c.check(s, "Menu › Settings opens Settings in the centre, and closes the list", d["03"] and wins(d["03"]) == [("Settings", "Centre")] and not d["03"]["menu"], str(wins(d["03"])))
    c.check(s, "I and L: pack right, log left, Settings closed", d["04"] and sorted(wins(d["04"])) == [("Log", "Left"), ("Pack", "Right")], str(wins(d["04"])))
    c.check(s, "windows fit 1600x900 and do not overlap", inside(d["04"]) and apart(d["04"]))
    c.check(s, "dragging the log to the right snaps it there and the pack takes the left", d["06"] and sorted(wins(d["06"])) == [("Log", "Right"), ("Pack", "Left")], str(wins(d["06"])))
    c.check(s, "after the swap, still inside and apart", inside(d["06"]) and apart(d["06"]))
    c.check(s, "✕ closes the pack", d["07"] and wins(d["07"]) == [("Log", "Right")], str(wins(d["07"])))
    c.check(s, "I opens the pack on its home anchor, replacing the log there", d["08"] and wins(d["08"]) == [("Pack", "Right")], str(wins(d["08"])))
    c.check(s, "Esc closes the top window", d["09"] and wins(d["09"]) == [], str(wins(d["09"])))
    c.check(s, "Esc with nothing open opens Menu", d["10"] and d["10"]["menu"])
    c.check(s, "Esc closes the Menu list first", d["11"] and not d["11"]["menu"])
    c.check(s, "Esc again opens Menu (and frees the cursor)", d["12"] and d["12"]["menu"] and "Esc with nothing open: Menu, cursor freed" in log(out))


def talk(run, c):
    s = "talk"
    a, b = residents(run)
    plan = ("ready;sync:scene;wait:2;shot:01_scene;cursor:0.5,0.12;wait:0.3;key:Enter:tap;wait:0.6;shot:02_room;dump:02;type:Good morning, all.;enter;wait:11.5;shot:03_room_note;dump:03;"
            "point:{A};wait:0.4;shot:04_hover;key:Enter:tap;wait:0.6;shot:05_to_them;dump:05;type:Hello there, good morning.;enter;wait:1.2;shot:06_said;dump:06;"
            "key:Enter:tap;wait:0.4;tab;wait:0.4;dump:07a;tab;wait:0.4;dump:07b;tab;wait:0.4;dump:07c;shot:07_tab;key:Escape:tap;wait:0.4;dump:08;"
            "key:KeyL:tap;wait:0.4;click:@log:tab:1;wait:0.4;shot:09_people;click:@log:person:0;wait:0.6;shot:10_window;dump:10;"
            "menu:f@id:{A};wait:0.5;click:@acts:0:window;wait:0.5;click:@person:more;wait:0.5;shot:11_more;click:@acts:0:introduce;wait:0.5;shot:11_intro;dump:11;quit").replace("{A}", str(a))
    out, code, text = drive(run, s, plan, places=[f"{a}:-2.5:2.0", f"{b}:-1.0:3.2"])
    c.check(s, "client ran and joined", code == 0, text[-300:])
    d = {k: dump(out, k) for k in ["02", "03", "05", "06", "07a", "07b", "07c", "08", "10", "11"]}
    L = log(out)
    t2 = (d["02"] or {}).get("typing") or {}
    c.check(s, "Enter with nobody under the cursor: to the room, in Log and people", t2.get("to") is None and t2.get("window") == "Log" and t2.get("label") == "To the room", json.dumps(t2))
    c.check(s, "the line goes to the room (to = 0)", 'say: "Good morning, all." to no one in particular' in L)
    c.check(s, "nobody took it up: the note says so", re.search(r'talk: room note "(Heard by \d+ — no one took it up|No one in earshot heard you)', L) is not None)
    t5 = (d["05"] or {}).get("typing") or {}
    c.check(s, "Enter while hovering someone: to them, in their window", t5.get("to") == a and t5.get("window") == f"Person{a}" and (f"Person{a}", "Left") in wins(d["05"]), json.dumps(t5))
    c.check(s, "the box names them by looks, not a name", t5.get("label", "").startswith("To a"), t5.get("label"))
    c.check(s, "Enter says it to them (human_say with to)", re.search(rf'say: "Hello there, good morning\." to #{a}\b', L) is not None)
    c.check(s, "their window stays after saying it", d["06"] and (f"Person{a}", "Left") in wins(d["06"]) and not d["06"]["typing"])
    tabs = [(d[k] or {}).get("typing") or {} for k in ["07a", "07b", "07c"]]
    c.check(s, "Tab: someone else in earshot (the window follows) and the room", any(t.get("to") not in (None, a) and t.get("window") == f"Person{t.get('to')}" for t in tabs) and any(t.get("to") is None and t.get("window") == "Log" for t in tabs), json.dumps(tabs))
    c.check(s, "Esc closes the box and its window", d["08"] and wins(d["08"]) == [] and not d["08"]["typing"], str(wins(d["08"])))
    c.check(s, "Log › People lists them; a click opens a person's window", d["10"] and any(w.startswith("Person") for w, _ in wins(d["10"])), str(wins(d["10"])))
    t11 = (d["11"] or {}).get("typing") or {}
    c.check(s, "their window › More… › Introduce yourself: an editable line to them", t11.get("words", "").startswith("I'm Verifier") and t11.get("to") == a and t11.get("window") == f"Person{a}", json.dumps(t11))
    rows = sql(run, f"SELECT kind, object, text FROM experience WHERE kind = 'said' AND object = {a}")
    c.check(s, "the authority's said row has to = the addressee", any("Hello there, good morning." in r.get("text", "") for r in rows), f"{len(rows)} said rows to #{a}")
    rows0 = sql(run, "SELECT kind, object, text FROM experience WHERE kind = 'said' AND object = 0")
    c.check(s, "and the room's line has to = 0", any("Good morning, all." in r.get("text", "") for r in rows0), f"{len(rows0)} said rows to the room")


def items(run, c):
    s = "items"
    a, b = residents(run)
    before = sum(r["qty"] for r in sql(run, f"SELECT item, qty FROM inventory WHERE owner = {a} AND item = 'berries'"))
    plan = ("ready;sync:scene;sync:kit;wait:1.5;menu:f@id:{A};wait:0.5;click:@acts:0:window;wait:0.6;dump:01;key:KeyI:tap;wait:0.6;shot:01_pack_person;dump:02;"
            "click:@pack:berries;wait:0.5;shot:02_item_acts;dump:03;key:Escape:tap;wait:0.3;slide:@pack:berries>@win:Person{A}:head:0.8;wait:2;shot:03_dropped;dump:04;"
            "menu:f@id:{A};wait:0.5;shot:04_hold_f;dump:05;click:@acts:0:give;wait:0.5;shot:05_give_sub;dump:06;click:@acts:1:berries;wait:2;shot:06_given;quit").replace("{A}", str(a))
    # The newcomer's berries may be gone from earlier runs: the scene grants four (admin).
    out, code, text = drive(run, s, plan, places=[f"{a}:-2.5:2.0", f"{b}:-1.0:3.2"], syncs=['kit=grant_items|{me}|"berries"|4'])
    c.check(s, "client ran and joined", code == 0, text[-300:])
    d = {k: dump(out, k) for k in ["01", "02", "03", "04", "05", "06"]}
    c.check(s, "hold-F list › Their window opens their window", d["01"] and (f"Person{a}", "Left") in wins(d["01"]), str(wins(d["01"])))
    c.check(s, "I opens the pack beside their window", d["02"] and sorted(wins(d["02"])) == sorted([(f"Person{a}", "Left"), ("Pack", "Right")]) and inside(d["02"]) and apart(d["02"]), str(wins(d["02"])))
    acts = (d["03"] or {}).get("acts") or {}
    c.check(s, "a click on berries lists the rules' acts with them", any("berries" in r for r in acts.get("rows", [])), json.dumps(acts))
    L = log(out)
    c.check(s, "berries slid onto their window are given (the rules' give)", re.search(rf"berries let go on #{a}: give berries", L) is not None)
    c.check(s, "hold F lists Talk and Their window first, and Give ›", (d["05"] or {}).get("acts") and (d["05"]["acts"]["rows"][:2] == ["talk", "their window"]) and any(r.startswith("give") for r in d["05"]["acts"]["rows"]), json.dumps((d["05"] or {}).get("acts")))
    c.check(s, "Give › opens the items beside the list", ((d["06"] or {}).get("acts") or {}).get("group") == "give")
    gives = len(re.findall(rf'"do":"give","item":"berries","qty":1,"target":\{{"id":{a}\}}', L))
    c.check(s, "two gives sent through human_act", gives == 2, f"{gives} sent")
    after = sum(r["qty"] for r in sql(run, f"SELECT item, qty FROM inventory WHERE owner = {a} AND item = 'berries'"))
    c.check(s, "the authority moved 2 berries to them", after - before == 2, f"{before} -> {after}")


def themes(run, c):
    s = "themes"
    plan = ("ready;wait:2;key:KeyL:tap;wait:0.3;key:KeyI:tap;wait:0.5;dump:01;shot:01_first;key:F4:tap;wait:0.8;shot:02_next;dump:02;key:F4:tap;wait:0.8;shot:03_next;dump:03;key:F4:tap;wait:0.8;shot:04_next;dump:04;"
            "click:@menu;wait:0.3;click:@menu:Settings;wait:0.6;click:@settings:theme:linen;wait:0.8;shot:05_linen;dump:05;quit")
    out, code, text = drive(run, s, plan)
    c.check(s, "client ran and joined", code == 0, text[-300:])
    d = {k: dump(out, k) for k in ["01", "02", "03", "04", "05"]}
    names = [((d[k] or {}).get("extra") or {}).get("theme") for k in ["01", "02", "03", "04"]]
    order = ["clear", "night", "linen", "walnut"]
    first = names[0]
    want = [order[(order.index(first) + i) % 4] for i in range(4)] if first in order else []
    c.check(s, "F4 cycles the themes in order", names == want, str(names))
    c.check(s, "each change is named on screen", len(re.findall(r"ui: Theme: \w+  ·  F4 changes it", log(out))) >= 3)
    c.check(s, "windows stay where they were through a change", all(sorted(wins(d[k])) == [("Log", "Left"), ("Pack", "Right")] for k in ["01", "02", "03", "04"]), str([wins(d[k]) for k in ["01", "02", "03", "04"]]))
    c.check(s, "Settings › Play › Look sets it", ((d["05"] or {}).get("extra") or {}).get("theme") == "linen")
    st = os.path.join(out, "settings.json")
    saved = json.load(open(st)).get("theme") if os.path.exists(st) else None
    c.check(s, "the settings file keeps it", saved == "linen", str(saved))


# Where the support scenario stands the player on Cullet (land metres; the plan's x + 510 and
# 784 - y, as of layout pass 1: the Ladder Wynd at plan x -52, the Marver's terrace at x 68..80)
# and what holds it up there:
# a kit fixture's file (part of its path) and whether it is tall enough to be an occluder, so the
# camera's fade (`envs::cutaway`) considers it at all.
SUPPORTS = [
    ("stairs", 458.0, 755.0, "stairs/stairs_ladder_wynd_strand_to_low", True),
    ("terrace", 584.0, 720.8, "marver_terrace/", False),
    ("quay", 450.0, 782.6, "quay/", False),
    # At the upper level's edge above a retaining wall: the drop's tiles keep you 1-1.5 m from
    # it, so it is beside you, never under you; it may fade when it stands between the camera
    # and you, as anything that hides you does.
    ("wall", 440.0, 751.6, "retaining_wall/wall_002", False),
]


def support(run, c):
    """What I stand on or step onto never fades (the owner's Cullet walk: the flight dithered away
    while climbing it). Needs a Cullet world (`--seed cullet`) and the cutaway's debug log."""
    s = "support"
    plan = "ready;wait:3"
    for name, *_ in SUPPORTS:
        plan += f";sync:{name};wait:6;shot:{name};dump:{name}"
    plan += ";quit"
    syncs = [f"{name}=place_at|{{me}}|{x}|{y}" for name, x, y, *_ in SUPPORTS]
    old = os.environ.get("RUST_LOG")
    os.environ["RUST_LOG"] = "info,wgpu=warn,naga=warn,living_game::envs=debug"
    try:
        out, code, text = drive(run, s, plan, syncs=syncs)
    finally:
        if old is None:
            os.environ.pop("RUST_LOG")
        else:
            os.environ["RUST_LOG"] = old
    c.check(s, "client ran and joined", code == 0, text[-300:])
    L = log(out)
    # The log in stretches, one per spot: from its sync step to the next.
    parts = re.split(r"live script: sync:(\w+)", L)
    seg = {parts[i]: parts[i + 1] for i in range(1, len(parts) - 1, 2)}
    for name, x, y, part, occluder in SUPPORTS:
        t = seg.get(name, "")
        held = set(re.findall(r"cutaway: (\S+) holds me up", t))
        faded = re.findall(r"cutaway: (\S+) fades to", t)
        mine = [f for f in held if part in f]
        if occluder:
            c.check(s, f"{name}: the cutaway finds what holds me up ({part})", bool(mine), f"held {sorted(held)}")
        # What held me up there, and the spot's own support, never fades there.
        bad = [f for f in faded if f in held or (not occluder and part in f)]
        c.check(s, f"{name}: nothing under or beside my feet fades", t != "" and not bad, f"faded {bad}" if t else "no log for this spot")
    c.check(s, "photographs of each spot", all(os.path.exists(os.path.join(out, f"{n}.png")) for n, *_ in SUPPORTS))


def pick(run, c):
    """Two people overlapping on screen: the cursor on the one in front (its chest, with the one
    behind standing where the cursor's ground point falls) names, hovers and addresses that one.
    The pick is one function for the nameplate, Enter and combat's target (living/game/src/pick.rs);
    before it, Enter took the hovered person nearest the cursor's ground point: the one behind."""
    s = "pick"
    a, b = residents(run)
    line = f"You in front, {int(time.time()) % 100000}."  # its own line: said rows from earlier drives don't count
    # The view faces north (yaw 0, sim -y). A stands ahead and to the left; B 1.5 m behind A along
    # the view, where the ray through A's chest meets the ground.
    plan = ("ready;frame:0;yaw:0;wait:1.5;sync:scene;wait:2;point:{A}:1.3;wait:0.8;shot:01_pointed;dump:01;"
            "key:Enter:tap;wait:0.6;shot:02_to_them;dump:02;type:{LINE};enter;wait:1.2;dump:03;key:Escape:tap;wait:0.6;"
            "point:{A}:1.3;wait:0.8;tap;wait:0.8;dump:04;key:Escape:tap;wait:0.4;quit").replace("{A}", str(a)).replace("{LINE}", line)
    out, code, text = drive(run, s, plan, places=[f"{a}:-3.0:-1.0", f"{b}:-3.0:-2.5"])
    c.check(s, "client ran and joined", code == 0, text[-300:])
    d = {k: dump(out, k) for k in ["01", "02", "03", "04"]}
    L = log(out)
    hov = [h.get("id") for h in (d["01"] or {}).get("hovered") or []]
    c.check(s, "the cursor on the one in front: only they are hovered (one nameplate)", hov == [a], f"hovered {hov}, under {(d['01'] or {}).get('under')}, in front #{a}, behind #{b}")
    t2 = (d["02"] or {}).get("typing") or {}
    c.check(s, "Enter addresses the one in front, in their window", t2.get("to") == a and t2.get("window") == f"Person{a}", json.dumps(t2))
    c.check(s, "the target plate is the one addressed", (d["02"] or {}).get("targeted") == a, str((d["02"] or {}).get("targeted")))
    c.check(s, "the line goes to them (human_say with to)", re.search(rf'say: "{re.escape(line)}" to #{a}\b', L) is not None)
    t4 = (d["04"] or {}).get("typing") or {}
    c.check(s, "a tap on the one in front talks to them (combat's target is the same pick)", t4.get("to") == a, json.dumps(t4))
    rows = sql(run, f"SELECT kind, object, text FROM experience WHERE kind = 'said' AND object = {a}")
    c.check(s, "the authority's said row has to = the one in front", any(line in r.get("text", "") for r in rows), f"{len(rows)} said rows to #{a}")


def cursor(d):
    c = ((d or {}).get("extra") or {}).get("cursor")
    return (c["x"], c["y"]) if c else None


def view(d):
    return ((d or {}).get("extra") or {}).get("view") or {}


def ground(d):
    return ((d or {}).get("extra") or {}).get("cursor_ground")


def turns(run, c):
    """The cursor while the view turns or zooms (Cullet walk 1, the owner: a pan turned the view
    and carried the cursor off with it). A two-finger pan, a pinch either way and a left drag,
    through the pointer's own paths (`pan:`, `pinch:`, `drag:`), with the cursor off-centre and
    nothing open: the cursor keeps its screen position (within 1 px), the view turns or zooms,
    and the ground under the cursor changes with the view."""
    s = "turns"
    plan = ("ready;wait:2;frame:0;cursor:0.72,0.62;wait:1;dump:01;shot:01_start;"
            "pan:300;wait:0.15;dump:02;shot:02_panning;wait:1.5;dump:03;shot:03_panned;"
            "pan:-500;wait:1.5;dump:04;shot:04_panned_back;"
            "pinch:0.3;wait:0.15;dump:05;wait:1.2;dump:06;shot:06_pinched_in;"
            "pinch:-0.4;wait:1.2;dump:07;shot:07_pinched_out;"
            "drag:250;wait:1.5;dump:08;shot:08_dragged;quit")
    out, code, text = drive(run, s, plan)
    c.check(s, "client ran and joined", code == 0, text[-300:])
    d = {k: dump(out, k) for k in ["01", "02", "03", "04", "05", "06", "07", "08"]}
    start = cursor(d["01"])
    c.check(s, "the cursor is off-centre with nothing open", start and abs(start[0] - 0.72 * W) <= 1 and abs(start[1] - 0.62 * H) <= 1 and not (d["01"] or {}).get("pointer_over_ui"), f"{start} over_ui {(d['01'] or {}).get('pointer_over_ui')}")

    def same(k):
        p = cursor(d[k])
        return p is not None and start is not None and abs(p[0] - start[0]) <= 1 and abs(p[1] - start[1]) <= 1, f"{k}: {p} vs {start}"

    def moved(a, b, m=1.0):
        ga, gb = ground(d[a]), ground(d[b])
        if not (ga and gb):
            return False, f"no ground point ({ga}, {gb})"
        dist = ((ga[0] - gb[0]) ** 2 + (ga[2] - gb[2]) ** 2) ** 0.5
        return dist > m, f"{dist:.2f} m"

    def yaw_turned(a, b, deg=10.0):
        ya, yb = view(d[a]).get("yaw"), view(d[b]).get("yaw")
        if ya is None or yb is None:
            return False, f"{ya} {yb}"
        t = (yb - ya + 180.0) % 360.0 - 180.0
        return abs(t) > deg, f"{t:+.1f} deg"

    for k, what in [("02", "mid-pan"), ("03", "after a pan"), ("04", "after a pan back")]:
        ok, det = same(k)
        c.check(s, f"pan: the cursor keeps its screen position {what} (1 px)", ok, det)
    ok, det = yaw_turned("01", "03")
    c.check(s, "pan: the view turned", ok, det)
    ok, det = moved("01", "03")
    c.check(s, "pan: the ground under the cursor follows the view", ok, det)
    for k, what in [("05", "mid-pinch"), ("06", "after a pinch in"), ("07", "after a pinch out")]:
        ok, det = same(k)
        c.check(s, f"pinch: the cursor keeps its screen position {what} (1 px)", ok, det)
    z = [view(d[k]).get("zoom") for k in ["04", "06", "07"]]
    c.check(s, "pinch: the view zoomed in, then out", None not in z and z[1] < z[0] - 0.05 and z[2] > z[1] + 0.05, str(z))
    ok, det = moved("04", "06", 0.3)
    c.check(s, "pinch: the ground under the cursor follows the zoom", ok, det)
    ok, det = same("08")
    c.check(s, "left drag: the cursor keeps its screen position (1 px)", ok, det)
    ok, det = yaw_turned("07", "08")
    c.check(s, "left drag: the view turned", ok, det)


# ---- facing sight (fov) --------------------------------------------------------------------

def wrap(a):
    a = math.fmod(a, 2 * math.pi)
    if a > math.pi:
        a -= 2 * math.pi
    elif a <= -math.pi:
        a += 2 * math.pi
    return a


def fov_within(sight, f, off, dist, glow, kept):
    """living_rules::sight::within (distance and angle; no sight line), ported for the check."""
    keep = kept or 0.0
    floor = min(f["near_m"], sight) + keep
    if dist <= floor:
        return True
    margin = f["margin_deg"] if kept is not None else 0.0
    deg = abs(math.degrees(wrap(off)))
    lit = max(sight, glow)
    if deg <= f["focal_deg"] + margin:
        ahead = lit
    elif deg <= f["side_deg"] + margin:
        ahead = max(sight * f["side_share"], glow)
    else:
        ahead = 0.0
    return dist <= max(ahead, min(f["near_m"], sight)) + keep


def heading_at(b, now_ms):
    """The authority's heading_at on a body row."""
    if not b.get("turn") or b.get("turn_s", 0) <= 0:
        return wrap(b["heading"])
    t = max(0, min(now_ms, b["next_ms"]) - b["t_ms"]) / 1000.0
    return wrap(b["heading"] + b["turn"] * min(t, b["turn_s"]))


def field_dumps(d):
    """The client's field dumps (`LIVING_SIGHT_FIELD_DUMP`): (meta, pgm bytes) in order."""
    out = []
    for n in sorted(f for f in os.listdir(d) if f.endswith(".json")):
        meta = json.load(open(os.path.join(d, n)))
        raw = open(os.path.join(d, n[:-5] + ".pgm"), "rb").read()
        out.append((meta, raw[-meta["size"] * meta["size"]:]))
    return out


def texel(meta, pix, x, y):
    i = int((x - meta["origin"][0]) / meta["texel"])
    j = int((y - meta["origin"][1]) / meta["texel"])
    n = meta["size"]
    return pix[j * n + i] if 0 <= i < n and 0 <= j < n else None


# The looks the scenario faces (live script `look:DEG`: 0 north, clockwise) and where the
# residents stand round the player (dx, dy metres; +y south; `place_at` puts them on tile
# centres): north and south at 5 m, east and west at 5.5 m (past the near ring's and side
# vision's reach and their keep metre, so behind or to the side they are clearly unseen), one at
# 1.4 m (the near ring), one 8 m to the south-east.
FOV_LOOKS = [0, 90, 180, 270]
FOV_PLACES = [(0.0, -5.0), (5.5, 0.0), (0.0, 5.0), (-5.5, 0.0), (1.0, -1.0), (5.7, 5.7)]
LIT = 100.0   # a light on someone (`glow`) the client can't know, at night: a comparison it could flip is left out
DAY_SIGHT = 11.0  # the shipped senses law's sight by day: no one is lit by day


def compare_fov(snap, dumps, me):
    """The authority's perceived set against the client's field at one look: per creature within
    15 m, whether the authority perceives it and whether the client's field shows its spot seen.
    Creatures the margins or a light could decide (the rule's answer differs with the keep margins
    or a glow) are counted apart, not compared."""
    rows = {r["query"].split(" FROM ")[1].split()[0]: r for r in snap}
    bodies = {b["id"]: b for b in rows["body"]["rows"]}
    seen = {p["body"] for p in rows["perceived"]["rows"]}
    at = rows["body"]["wall_ms"]
    mine = bodies.get(me)
    prior = [d for d in dumps if d[0]["wall_ms"] <= at + 300 and d[0].get("facing")]
    if not mine or not prior:
        return None
    meta, pix = prior[-1]
    fc = meta["facing"]
    sight, f = fc["sight"], fc
    h_auth = heading_at(mine, at)
    eye = (mine["x"], mine["y"])
    out = {"heading_client": math.degrees(fc["heading"]), "heading_authority": math.degrees(h_auth), "dump": meta["n"], "same": [], "differ": [], "margin": []}
    for bid, b in bodies.items():
        if bid == me:
            continue
        d = math.hypot(b["x"] - eye[0], b["y"] - eye[1])
        if d > 15.0:
            continue
        off = wrap(math.atan2(b["y"] - eye[1], b["x"] - eye[0]) - h_auth)
        glows = (0.0,) if sight >= DAY_SIGHT else (0.0, LIT)
        answers = {fov_within(sight, f, off, d, g, k) for g in glows for k in (None, 1.0)}
        v = texel(meta, pix, b["x"], b["y"])
        # What the screen shows seen: the field there, within the radius (the field reaches on
        # past it along the focal angle, for the radius's soft band to draw that edge).
        shown = None if v is None else (v >= 128 and d <= sight)
        row = {"id": bid, "dist": round(d, 2), "off_deg": round(math.degrees(off), 1), "authority": bid in seen, "field": shown}
        if len(answers) > 1:
            out["margin"].append(row)
        elif row["field"] == row["authority"]:
            out["same"].append(row)
        else:
            out["differ"].append(row)
    return out


def field(run, c):
    """Facing sight (`fov_on`): off, the client draws no field (its dumps have no facing); on (F5
    through the admin link), the field and its readout appear, and at four looks the authority's
    perceived set matches the client's field; a walking look is held at `look_walk_deg`; a
    release snaps a walk back to its travel and leaves a standing body facing where it was; the
    Settings switch turns it off again; each switch is a law_change row."""
    s = "field"
    ids = residents(run, len(FOV_PLACES))
    if len(ids) < len(FOV_PLACES):
        c.check(s, f"{len(FOV_PLACES)} residents to place", False, f"only {ids}")
        return
    # Off at the start: the law as shipped (a re-run starts from it again).
    subprocess.run([sys.executable, V, "call", "--run", run, "--as-admin", "set_world_law", '["fov_on", "false"]'], capture_output=True, text=True)
    changes0 = sql(run, "SELECT id FROM law_change")
    snap = lambda n: f"{n}=sql|SELECT id, x, y, heading, turn, turn_s, t_ms, next_ms FROM body;sql|SELECT body FROM perceived WHERE viewer = 0x{{ident}};sql|SELECT key, target, bearing, band FROM heard WHERE listener = {{me}}"
    body = lambda n: f"{n}=sql|SELECT id, x, y, heading, turn, turn_s, t_ms, next_ms, vx, vy FROM body WHERE id = {{me}}"
    plan = "ready;frame:0;yaw:0;wait:1.5;sync:scene;wait:2;dump:01_off;shot:01_off;key:F5:tap;wait:2.5;dump:02_on;shot:02_on"
    for deg in FOV_LOOKS:
        plan += f";look:{deg};wait:2.5;sync:h{deg};dump:h{deg};shot:h{deg}"
    # Walking north with the look east (90° off): held at look_walk_deg; F3 (to "where you walk")
    # releases it while walking, then standing.
    plan += (";look:90;hold:0;wait:2;sync:walk;key:F3:tap;wait:1.5;sync:released;stop;wait:1.5;key:F3:tap;look:270;wait:2;sync:looked;key:F3:tap;wait:1.5;sync:stood;"
             "click:@menu;wait:0.4;click:@menu:Settings;wait:0.8;shot:03_settings_on;dump:03;click:@settings:facing_sight;wait:2.5;shot:04_settings_off;dump:04;quit")
    syncs = [snap(f"h{d}") for d in FOV_LOOKS] + [body(n) for n in ("walk", "released", "looked", "stood")]
    places = [f"{i}:{dx}:{dy}" for i, (dx, dy) in zip(ids, FOV_PLACES)]
    env = {"LIVING_GAME_CONTROL": "cursor", "RUST_LOG": "info,wgpu=warn,naga=warn,living_game::controls=debug"}
    old = {k: os.environ.get(k) for k in list(env) + ["LIVING_SIGHT_FIELD_DUMP"]}
    name = f"{s}-{THEME}" if THEME else s
    fdir = os.path.join(ROOT, ".local/living/verify", run, "ui", name, "fields")
    if os.path.isdir(fdir):
        for f in os.listdir(fdir):
            os.remove(os.path.join(fdir, f))
    os.environ.update(env, LIVING_SIGHT_FIELD_DUMP=fdir)
    try:
        out, code, text = drive(run, s, plan, places=places, syncs=syncs, extra=["--admin-link"])
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    c.check(s, "client ran and joined", code == 0, text[-300:])
    c.check(s, "the admin token file was deleted after the drive", "admin token file deleted" in text and not any(os.scandir(os.path.join(ROOT, ".local/living/verify", run, "private"))))
    L = log(out)
    d = {k: dump(out, k) for k in ["01_off", "02_on", "03", "04"] + [f"h{x}" for x in FOV_LOOKS]}
    fs = lambda k: ((d[k] or {}).get("extra") or {}).get("facing_sight") or {}
    dumps = field_dumps(fdir) if os.path.isdir(fdir) else []
    before_on = [m for m, _ in dumps if m["wall_ms"] < min([m["wall_ms"] for m, _ in dumps if m.get("facing")] or [1 << 62])]
    c.check(s, "off: the client knows facing sight is off and draws no field", fs("01_off").get("known") and fs("01_off").get("on") is False and before_on and all(m.get("facing") is None for m in before_on), json.dumps(fs("01_off")))
    c.check(s, "the admin link opened (a play scene's law_toggle)", "facing: admin link open" in L)
    on = fs("02_on")
    want = {"focal_deg": 70.0, "side_deg": 110.0, "side_share": 1 / 3, "near_m": None, "margin_deg": 10.0}
    fv = on.get("field") or {}
    c.check(s, "F5 turns it on: the field has the law's five values", on.get("on") and all(abs(fv.get(k, -1) - v) < 1e-3 for k, v in want.items() if v is not None) and fv.get("near_m") in (2.0, 3.0), json.dumps(on))
    c.check(s, "the readout shows the five values when it changes", re.search(r"facing: Facing sight on — Focal ±70° · side ±110° at 33% of sight · near [23] m all round · margin 10°", L) is not None)
    toasts = (d["02_on"] or {}).get("toasts") or []
    c.check(s, "…on screen, as two notes", any(t.startswith("Facing sight on") for t in toasts) and any(t.startswith("Focal ±70°") for t in toasts), str(toasts))
    sc = json.load(open(os.path.join(out, "scene.json"))) if os.path.exists(os.path.join(out, "scene.json")) else {}
    me = sc.get("me")
    snaps = sc.get("snaps") or {}
    results = {}
    for deg in FOV_LOOKS:
        r = compare_fov(snaps.get(f"h{deg}") or [], dumps, me) if snaps.get(f"h{deg}") else None
        results[deg] = r
        if r is None:
            c.check(s, f"look {deg}°: a snapshot and a field dump", False)
            continue
        want_h = math.degrees(wrap(math.radians(deg - 90)))
        dh = abs(math.degrees(wrap(math.radians(r["heading_client"] - r["heading_authority"]))))
        dl = abs(math.degrees(wrap(math.radians(r["heading_authority"] - want_h))))
        c.check(s, f"look {deg}°: human_face turned the authority's body (within 3°), the field follows it (within 3°)", dl < 3.0 and dh < 3.0, f"authority {r['heading_authority']:.1f}°, client {r['heading_client']:.1f}°, wanted {want_h:.1f}°")
        seen_n = sum(1 for x in r["same"] if x["authority"])
        unseen_n = sum(1 for x in r["same"] if not x["authority"])
        c.check(s, f"look {deg}°: the authority's perceived set matches the client's field", not r["differ"] and seen_n >= 2 and unseen_n >= 2, f"differ {r['differ']}; {seen_n} seen and {unseen_n} unseen agree; {len(r['margin'])} at a margin")
    json.dump(results, open(os.path.join(out, "fov_compare.json"), "w"), indent=1)
    # Heard, not seen: the authority's heard rows at each look against the client's marks then.
    heard_ok, heard_n, stray = 0, 0, []
    for deg in FOV_LOOKS:
        rows = {r["query"].split(" FROM ")[1].split()[0]: r for r in snaps.get(f"h{deg}") or []}
        if "heard" not in rows:
            continue
        seen_ids = {p["body"] for p in rows["perceived"]["rows"]}
        marks = {int(m["key"], 16): m for m in (((d[f"h{deg}"] or {}).get("extra") or {}).get("heard") or []) if m.get("live")}
        for h in rows["heard"]["rows"]:
            heard_n += 1
            m = marks.get(int(h["key"]))
            heard_ok += bool(m and m["bearing"] == h["bearing"] and m["band"] == h["band"])
            if h["target"] in seen_ids:
                stray.append(h)
    c.check(s, "heard, not seen: a mark per heard row, by its key, its way and band", heard_n >= 3 and heard_ok >= 0.8 * heard_n, f"{heard_ok} of {heard_n} matched")
    c.check(s, "…and none of them is someone in sight", not stray, str(stray[:3]))
    c.check(s, "…marks fade after their rows go", re.search(r"heard: mark [0-9a-f]{16} \(\w+\) faded", L) is not None)
    def b(n):
        rows = (snaps.get(n) or [{}])[0].get("rows") or []
        return rows[0] if rows else None
    walk, rel, looked, stood = b("walk"), b("released"), b("looked"), b("stood")
    north = -90.0
    # The client releases its look while a direction is held (controls::FACE_WHILE_MOVING off,
    # until look-2): walking north with the cursor east, the body faces and walks north. With it
    # on, the authority would hold the body 30° toward the look (look_walk_deg).
    face_moving = re.search(r"pub const FACE_WHILE_MOVING: bool = (\w+);", open(os.path.join(ROOT, "living/game/src/controls.rs")).read())
    face_moving = face_moving and face_moving.group(1) == "true"
    if walk:
        h = math.degrees(heading_at(walk, snaps["walk"][0]["wall_ms"]))
        off = abs(math.degrees(wrap(math.radians(h - north))))
        speed = math.hypot(walk["vx"], walk["vy"])
        if face_moving:
            c.check(s, "walking north with the look east: the body turns 30° toward it, not more (look_walk_deg)", abs(off - 30.0) < 4.0 and speed > 0.5, f"heading {h:.1f}°, speed {speed:.2f}")
        else:
            c.check(s, "walking north with the cursor east: the look is released while moving, the body faces its travel", off < 4.0 and speed > 0.5, f"heading {h:.1f}°, speed {speed:.2f}")
        moving_rel = re.search(r"look: human_face\(0\.000, 0\.000\)", L) is not None
        c.check(s, "…the release went as human_face(0, 0)", moving_rel or face_moving)
    if rel:
        h = math.degrees(heading_at(rel, snaps["released"][0]["wall_ms"]))
        c.check(s, "a release while walking snaps back to the travel (north)", abs(math.degrees(wrap(math.radians(h - north)))) < 4.0, f"heading {h:.1f}°")
    if looked and stood:
        h1 = math.degrees(heading_at(looked, snaps["looked"][0]["wall_ms"]))
        h2 = math.degrees(heading_at(stood, snaps["stood"][0]["wall_ms"]))
        c.check(s, "standing, a look west turns the body there and a release leaves it there", abs(abs(h1) - 180.0) < 4.0 and abs(math.degrees(wrap(math.radians(h2 - h1)))) < 2.0, f"looked {h1:.1f}°, after the release {h2:.1f}°")
    sends = len(re.findall(r"look: human_face\(", L))
    refusals = re.findall(r"face refused: ([^\n]+)", L)
    c.check(s, "looks went through human_face, none refused for anything but the input bucket", sends >= 6 and all("too many movement inputs" in x for x in refusals), f"{sends} sends; refusals {refusals[:3]}")
    c.check(s, "Settings › Play shows facing sight on, its switch and the values", fs("03").get("on") and "settings:facing_sight" in ((d["03"] or {}).get("tags") or {}))
    c.check(s, "the Settings switch turns it off; the field goes", fs("04").get("on") is False and dumps and dumps[-1][0].get("facing") is None, json.dumps(fs("04")))
    c.check(s, "…and the readout says so", re.search(r"facing: Facing sight off", L) is not None)
    changes = sql(run, "SELECT id, name, old, new, revision FROM law_change")
    new = [r for r in changes if r["id"] not in {x["id"] for x in changes0}]
    c.check(s, "each switch is a law_change row (fov_on false → true → false)", [(r["name"], r["new"]) for r in sorted(new, key=lambda r: r["id"])] == [("fov_on", "true"), ("fov_on", "false")], str(new))


SCENARIOS = {"field": field, "windows": windows, "talk": talk, "items": items, "themes": themes, "pick": pick, "turns": turns, "support": support}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("scenarios", nargs="*")
    a = ap.parse_args()
    if not f"verify-{a.run}".startswith("verify-ui-"):
        sys.exit("verify-ui runs use run names ui-* (worlds verify-ui-*)")
    c = Checks()
    # `support` needs a Cullet world (`--seed cullet`), the others the island's residents.
    for name in a.scenarios or [k for k in SCENARIOS if k != "support"]:
        if name not in SCENARIOS:
            sys.exit(f"unknown scenario {name}; known: {', '.join(SCENARIOS)}")
        SCENARIOS[name](a.run, c)
    p = os.path.join(ROOT, ".local/living/verify", a.run, "ui", "checks.json")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    json.dump(c.rows, open(p, "w"), indent=1)
    failed = [r for r in c.rows if not r["ok"]]
    print(f"{len(c.rows) - len(failed)} passed, {len(failed)} failed; {p}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
