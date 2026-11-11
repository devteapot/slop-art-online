#!/usr/bin/env python3
"""Run verify-ui scenarios on a verify-ui-* world and check what they did.

  check.py --run RUN [SCENARIO ...]      scenarios: windows talk items themes pick turns look-walk support (default: all but support)
  LIVING_GAME_THEME=night check.py …     the same in a theme (evidence in <scenario>-<theme>/)

Each scenario drives the real client headless through drive.py (one client run per scenario),
then checks the game UI's dumps (`dump:` steps: open windows, anchors, rectangles, the box and
whom it addresses, the weapon), the client log (what was sent through the player reducers) and,
for items, the authority's rows (owner SQL through verify.py). It prints PASS or FAIL per check
and writes `.local/living/verify/RUN/ui/checks.json`. Exit 1 when any check fails.

Two residents are placed beside the player and held still for the talk and items scenarios
(admin `place_at` and `set_behavior`: scene setup, not player acts).
"""
import argparse, json, os, re, subprocess, sys, time

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


def drive(run, name, plan, places=(), syncs=(), token=None):
    # A run per theme keeps its own evidence (`LIVING_GAME_THEME=night check.py …`).
    name = f"{name}-{THEME}" if THEME else name
    cmd = [sys.executable, os.path.join(HERE, "drive.py"), "--run", run, "--name", name, "--plan", plan, "--timeout", "420"]
    if token:
        cmd += ["--token", token]
    for p in places:
        cmd += ["--place", p]
    for s in syncs:
        cmd += ["--sync", s]
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
    # The gives are proven by their outcomes, not by the receiver's berries: a resident is free
    # until the scene holds it (sync:scene, once the client is ready) and eats, gathers and gives
    # berries meanwhile, so a count taken before the drive is no baseline (verify-player's rule).
    t0 = int(time.time() * 1000) - 1000
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
    me = (json.load(open(os.path.join(out, "scene.json"))) if os.path.exists(os.path.join(out, "scene.json")) else {}).get("me")
    # The authority goes on after the client quits: wait up to 10 s for both outcomes.
    gave, gifts = [], []
    for _ in range(20):
        gave = [r for r in sql(run, f"SELECT at_ms, text FROM experience WHERE observer = {me} AND kind = 'act'") if r.get("at_ms", 0) >= t0] if me else []
        gifts = [r for r in sql(run, f"SELECT at_ms, text FROM experience WHERE observer = {a} AND kind = 'gift'") if r.get("at_ms", 0) >= t0]
        if len([r for r in gave if "gave 1 berries" in r["text"]]) >= 2 and len(gifts) >= 2:
            break
        time.sleep(0.5)
    done = [r["text"] for r in gave if "gave 1 berries" in r["text"]]
    c.check(s, "the rules carried out both gives (the player's act outcomes)", len(done) == 2, f"{len(done)} done; outcomes {[r['text'] for r in gave]}")
    c.check(s, "and both reached them (their gift experiences)", len(gifts) == 2, f"{len(gifts)} gifts")


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
# and what holds it up there: a kit fixture's file (part of its path); whether it is tall enough to
# be an occluder, so the camera's fade (`envs::cutaway`) considers it at all; and whether it is what
# I walk on there (a flight, a terrace, the quay: never faded), or only beside me (a retaining wall
# below the edge I stand on, which may fade when it stands between the camera and me).
SUPPORTS = [
    ("stairs", 458.0, 755.0, "stairs/stairs_ladder_wynd_strand_to_low", True, True),
    ("terrace", 584.0, 720.8, "marver_terrace/", False, True),
    ("quay", 450.0, 782.6, "quay/", False, True),
    # At the upper level's edge above a retaining wall: the drop's tiles keep you 1-1.5 m from
    # it, so it is beside you, never under you; it may fade when it stands between the camera
    # and you, as anything that hides you does.
    ("wall", 440.0, 751.6, "retaining_wall/wall_002", False, False),
]
# Where the player stands first, away from every spot: the cutaway names what holds me up once,
# as I come onto it, and the character keeps its place between drives.
AWAY = (540.5, 766.5)


def support(run, c):
    """What I stand on or step onto never fades (the owner's Cullet walk: the flight dithered away
    while climbing it). Needs a Cullet world (`--seed cullet`) and the cutaway's debug log."""
    s = "support"
    plan = "ready;sync:away;wait:3"
    for name, *_ in SUPPORTS:
        plan += f";sync:{name};wait:6;shot:{name};dump:{name}"
    plan += ";quit"
    syncs = [f"away=place_at|{{me}}|{AWAY[0]}|{AWAY[1]}"] + [f"{name}=place_at|{{me}}|{x}|{y}" for name, x, y, *_ in SUPPORTS]
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
    for name, x, y, part, occluder, walked in SUPPORTS:
        t = seg.get(name, "")
        held = set(re.findall(r"cutaway: (\S+) holds me up", t))
        faded = re.findall(r"cutaway: (\S+) fades to", t)
        mine = [f for f in held if part in f]
        if occluder:
            c.check(s, f"{name}: the cutaway finds what holds me up ({part})", bool(mine), f"held {sorted(held)}")
            # Only the plan's own flight is there: no other kit file of its kind drawn on it
            # (stairs-place: a Store Wynd flight stood at the Ladder Wynd's foot).
            folder = part.split("/")[0] + "/"
            others = sorted(f for f in held if folder in f and part not in f)
            c.check(s, f"{name}: no other {folder[:-1]} model stands there", not others, f"also held {others}")
        # What held me up there, and what I walk on there, never fades there.
        bad = [f for f in faded if f in held or (walked and part in f)]
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


# The look-walk presets (`living/game/src/twist.rs` `LookWalk::preset`): head and chest limits,
# the body's limit and time constant (s). Kept in step with the client by hand.
LOOK_WALK = {"head": (60, 0, 45, 0.22), "chest": (50, 40, 45, 0.35), "loose": (60, 55, 45, 0.6)}


def wrapd(a):
    return (a + 180.0) % 360.0 - 180.0


def feet_log(out):
    p = os.path.join(out, "feet.jsonl")
    rows = []
    if os.path.exists(p):
        for line in open(p, errors="replace"):
            try:
                rows.append(json.loads(line))
            except ValueError:
                pass
    return [r for r in rows if r.get("sim") and r.get("t") is not None]


def look_walk_one(run, c, preset):
    """Walk while looking 0/45/90/135° off the travel (steady), then turn the travel 90° and 180°
    with the look held (sudden), in the cursor scheme, with the feet log on. Checks: the head and
    chest within the preset's limits; the legs eased (no frame jump); no crossing in steady walking
    within the head+chest limit; crossing after a sudden turn gone within 3 body_s + 0.6 s; ground
    speed the same looking aside as straight."""
    s = f"look-walk:{preset}"
    head, chest, body, body_s = LOOK_WALK[preset]
    upper = head + chest
    # Compass degrees (0 north, 90 east); each steady segment walks 6 s east or west.
    steady = [(0, 90, 90), (45, 270, 315), (90, 90, 180), (135, 270, 45)]
    # Open grass west of Brackenford on the island seed (no roads, nothing to steer round for
    # 10 m either way), placed there by admin `place_at` (scene setup).
    # The drawn body catches up a short teleport at 1.2 m/s: wait it out before walking.
    # A close camera for the photographs and the recording; the first-time tip out of the way.
    plan = f"ready;click:@tip:ok;sync:spot;wait:5;frame:0;view:28:5.5;lookwalk:{preset};wait:1;"
    for off, walk, look in steady:
        plan += f"look:{look};wait:0.6;hold:{walk};wait:4;shot:steady{off};wait:2;stop;wait:0.8;"
    plan += ("look:0;wait:0.6;hold:0;wait:3;hold:90;wait:0.35;shot:sudden90;wait:3.6;stop;wait:0.8;"
             "look:180;wait:0.6;hold:180;wait:3;hold:0;wait:0.35;shot:sudden180;wait:3.6;stop;wait:0.5;quit")
    # `LOOK_WALK_TAG=before` keeps a second set (another client: CARGO_TARGET_DIR).
    name = f"look-walk-{preset}" + (f"-{os.environ['LOOK_WALK_TAG']}" if os.environ.get("LOOK_WALK_TAG") else "")
    out_dir = os.path.join(ROOT, ".local/living/verify", run, "ui", f"{name}-{THEME}" if THEME else name)
    os.makedirs(out_dir, exist_ok=True)
    env_keep = {k: os.environ.get(k) for k in ["LIVING_GAME_FEET", "LIVING_GAME_CONTROL", "LIVING_GAME_RECORD"]}
    os.environ["LIVING_GAME_FEET"] = os.path.join(out_dir, "feet.jsonl")
    os.environ["LIVING_GAME_CONTROL"] = "cursor"
    if os.environ.get("LOOK_WALK_RECORD"):
        os.environ["LIVING_GAME_RECORD"] = os.path.join(out_dir, "record")
    try:
        if os.environ.get("LOOK_WALK_REUSE") and os.path.exists(os.path.join(out_dir, "feet.jsonl")):
            # Check the last drive's log again (iterating on the checks).
            out, code, text = out_dir, 0, "reused"
        else:
            out, code, text = drive(run, name, plan, syncs=[f"spot=place_at|{{me}}|{LOOK_WALK_SPOT[0]}|{LOOK_WALK_SPOT[1]}"], token=os.environ.get("LOOK_WALK_TOKEN"))
    finally:
        for k, v in env_keep.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    c.check(s, "client ran and joined", code == 0, text[-300:])
    rows = feet_log(out)
    c.check(s, "the feet log recorded the walk", len(rows) > 300, f"{len(rows)} frames")
    if len(rows) < 300:
        return {}
    # Per frame: drawn ground speed, the legs' yaw (the model root's: sim + 180°, `live.rs`
    # `yaw_of` turned by π), crossing.
    import math
    FORWARD = ("walk", "walk_brisk", "run", "run_fast", "walk_back")
    for i, r in enumerate(rows):
        q = rows[i - 1] if i else r
        r["dt"] = r["t"] - q["t"]
        r["v"] = (((r["sim"][0] - q["sim"][0]) ** 2 + (r["sim"][1] - q["sim"][1]) ** 2) ** 0.5 / r["dt"]) if r["dt"] > 0 else 0.0
        g = dict(r.get("gaits") or [])
        # The crossover takes cross by design; the forward and back gaits must not, in the legs'
        # own frame (the diagonals' feet trace across it by design, as the clip lab accepted).
        r["cross_w"] = sum(w for n, w in g.items() if "cross" in n)
        fwd = sum(w for n, w in g.items() if n in FORWARD) >= 0.8
        legs = math.radians(r["yaw"])
        sep = (r["la"][0] - r["ra"][0]) * -math.sin(legs) + (r["la"][2] - r["ra"][2]) * math.cos(legs)
        r["sep_raw"] = sep if fwd else None
    walking = [r for r in rows if r["v"] > 0.8 and r.get("heading") is not None]
    def off_of(r):
        return wrapd(r["look"] - r["heading"]) if r.get("look") is not None else None
    straight = [r for r in walking if off_of(r) is not None and abs(off_of(r)) < 3 and r.get("sep_raw") is not None]
    if not straight:
        c.check(s, "found straight walking to calibrate", False)
        return {}
    import statistics
    # Which side is the left foot in the legs' frame: from straight walking.
    sep_sign = 1.0 if statistics.median(r["sep_raw"] for r in straight) >= 0 else -1.0
    for r in rows:
        r["legs_off"] = wrapd(r["yaw"] - 180.0 - r["heading"]) if r.get("heading") is not None else None
        r["sep"] = r["sep_raw"] * sep_sign if r.get("sep_raw") is not None else None
        r["crossed"] = r["cross_w"] > 0.25 or (r["sep"] is not None and r["sep"] < -0.03)
    # Segments: consecutive walking frames with the same look (to 1°) and travel (to 5°).
    segs, cur = [], []
    for r in walking:
        if cur and (abs(wrapd(r["look"] - cur[-1]["look"])) > 1 or abs(wrapd(r["heading"] - cur[-1]["heading"])) > 5 or r["t"] - cur[-1]["t"] > 0.3):
            segs.append(cur)
            cur = []
        cur.append(r)
    if cur:
        segs.append(cur)
    result = {"preset": preset, "segments": []}
    base_v = None
    # Exact limits on what the client asked of the bones (Motion), and the bones as drawn.
    nk = max(abs(r.get("neck") or 0) for r in rows)
    ch = max(abs((r.get("twist") or 0) - (r.get("neck") or 0)) for r in rows)
    c.check(s, f"asked: neck and head within {head}°, spine and chest within {chest}°", nk <= head + 0.1 and ch <= chest + 0.1, f"neck {nk:.1f}, chest {ch:.1f}")
    # As drawn: the head from the chest, and the chest from the legs (the model root; the hips
    # sway ±10° in a walk), against what was asked, by median over walking frames.
    dn = [wrapd(r["head_yaw"] - r["chest_yaw"]) - r["neck"] for r in walking if r.get("head_yaw") is not None and r.get("neck") is not None]
    dc = [wrapd(r["chest_yaw"] - r["yaw"]) - (r["twist"] - r["neck"]) for r in walking if r.get("chest_yaw") is not None and r.get("twist") is not None]
    mn, mc = (statistics.median(dn) if dn else 99), (statistics.median(dc) if dc else 99)
    c.check(s, "drawn: the head turns from the chest and the chest from the legs as asked (median within 8°)", abs(mn) <= 8 and abs(mc) <= 8, f"head {mn:+.1f}°, chest {mc:+.1f}° off what was asked")
    hn = max((abs(wrapd(r["head_yaw"] - r["chest_yaw"])) for r in walking if r.get("head_yaw") is not None), default=0)
    c.check(s, f"drawn: the head never more than {head} + 15° from the chest", hn <= head + 15, f"max {hn:.1f}°")
    # Frames over 50 ms (a headless hitch) are left out: a take turns at its own rate over them.
    jumps = [abs(wrapd(rows[i]["yaw"] - rows[i - 1]["yaw"])) for i in range(1, len(rows)) if rows[i]["dt"] <= 0.05]
    hitches = sum(1 for r in rows if r["dt"] > 0.05)
    c.check(s, "the legs come round eased: no frame turns them more than 15°", jumps and max(jumps) <= 15.0, f"max {max(jumps or [0]):.1f}° a frame ({hitches} frames over 50 ms left out)")
    for off, walk, look in steady:
        seg = max((g for g in segs if g and abs(abs(off_of(g[0])) - off) < 6), key=len, default=None)
        if not seg or seg[-1]["t"] - seg[0]["t"] < 3.5:
            c.check(s, f"steady {off}°: a segment of at least 3.5 s", False, f"{len(seg or [])} frames")
            continue
        t0 = seg[0]["t"] + 2.0
        st = [r for r in seg if r["t"] >= t0]
        # The drawn speed: the median of 0.5 s windows' net displacement (the drawn track's
        # per-frame steps jitter at segment renewals, and a window over a snap is an outlier).
        wins, j = [], 0
        for i, r in enumerate(st):
            while st[j]["t"] < r["t"] - 0.5:
                j += 1
            if r["t"] - st[j]["t"] >= 0.45:
                wins.append(((r["sim"][0] - st[j]["sim"][0]) ** 2 + (r["sim"][1] - st[j]["sim"][1]) ** 2) ** 0.5 / (r["t"] - st[j]["t"]))
        v = statistics.median(wins) if wins else 0.0
        # The authority's segment speed is the ground speed the rules give the body.
        auth = statistics.median(r["seg"][2] for r in st if r.get("seg"))
        crossed = [r for r in st if r["crossed"]]
        legs = statistics.median(abs(r["legs_off"]) for r in st if r["legs_off"] is not None)
        # Forward: turned toward the look by what the head and chest leave, at most `body`;
        # backwards (past the back limit): the same from the travel's reverse.
        want = 180.0 - min(max((180 - off) - upper, 0), body) if off > LOOK_WALK_BACK.get(preset, 135) else min(max(off - upper, 0), body)
        row = {"off": off, "speed": round(v, 3), "authority_speed": auth, "legs_off_median": round(legs, 1), "legs_want": want, "crossed_frames": len(crossed), "frames": len(st),
               "min_sep_m": round(min((r["sep"] for r in st if r["sep"] is not None), default=0), 3), "cross_weight_max": round(max(r["cross_w"] for r in st), 2)}
        result["segments"].append(row)
        if off == 0:
            base_v, base_auth = v, auth
        if off <= upper:
            c.check(s, f"steady {off}° (within head+chest {upper}°): no crossing", not crossed, f"{len(crossed)}/{len(st)} frames, min sep {row['min_sep_m']} m, cross weight {row['cross_weight_max']}")
        else:
            c.check(s, f"steady {off}° (past head+chest): no crossing once the body has come round", not crossed, f"{len(crossed)}/{len(st)} frames")
        c.check(s, f"steady {off}°: the legs settle {want:.0f}° off the travel (±8°)", abs(legs - want) <= 8, f"{legs:.1f}°")
        if base_v and off:
            c.check(s, f"steady {off}°: the authority's ground speed as straight (±2%)", abs(auth / base_auth - 1) <= 0.02, f"{auth:.3f} vs {base_auth:.3f} m/s")
            c.check(s, f"steady {off}°: the drawn speed as straight (±8%)", abs(v / base_v - 1) <= 0.08, f"{v:.2f} vs {base_v:.2f} m/s")
    # Sudden turns: the travel turns 90° (then 180°) with the look held.
    limit = 3 * body_s + 0.6
    for turn, look_c in [(90, 0), (180, 180)]:
        lk = wrapd(-90 + look_c)  # compass to sim degrees
        cand = [i for i in range(1, len(rows)) if rows[i].get("look") is not None and abs(wrapd(rows[i]["look"] - lk)) < 1 and rows[i].get("heading") is not None and rows[i - 1].get("heading") is not None
                and abs(wrapd(rows[i - 1]["heading"] - lk)) < 20 and abs(wrapd(rows[i]["heading"] - lk)) >= 20]
        if not cand:
            c.check(s, f"sudden {turn}°: found the turn", False)
            continue
        i0 = cand[0]
        t_s = rows[i0]["t"]
        after = [r for r in rows[i0:] if r["t"] - t_s < 3.5 and r["v"] > 0.5]
        crossed = [r for r in after if r["crossed"]]
        last = (crossed[-1]["t"] - t_s) if crossed else 0.0
        result[f"sudden{turn}"] = {"crossed_frames": len(crossed), "last_cross_s": round(last, 2), "limit_s": round(limit, 2), "cross_weight_max": round(max([r["cross_w"] for r in after] or [0]), 2)}
        c.check(s, f"sudden {turn}°: any crossing ends within {limit:.2f} s", last <= limit, f"last crossing {last:.2f} s after the turn ({len(crossed)} frames)")
    json.dump(result, open(os.path.join(out, "look_walk.json"), "w"), indent=1)
    return result


LOOK_WALK_BACK = {"head": 130, "chest": 135, "loose": 155}
LOOK_WALK_SPOT = (300.0, 330.0)


def look_walk(run, c):
    """`look-walk` (play-test 5, item 2): every preset, or `LOOK_WALK_PRESETS=chest,head`;
    `LOOK_WALK_REUSE=1` checks the last drives' feet logs again, `LOOK_WALK_RECORD=1` also records
    the session (`LIVING_GAME_RECORD`, stills for a video), `LOOK_WALK_TOKEN=FILE` walks another
    character (a tired one walks at 0.6 of the pace, where the old client crossed its legs)."""
    for p in [x for x in os.environ.get("LOOK_WALK_PRESETS", "head,chest,loose").split(",") if x]:
        look_walk_one(run, c, p)
    if os.environ.get("LOOK_WALK_REUSE"):
        return
    # Settings › Play › Looking aside sets the preset and the settings file keeps it.
    s = "look-walk:settings"
    plan = ("ready;wait:1.5;click:@menu;wait:0.3;click:@menu:Settings;wait:0.6;shot:01_play;click:@settings:look_walk:loose;wait:0.5;dump:02;shot:02_loose;"
            "click:@settings:look_walk:head;wait:0.5;dump:03;quit")
    old = os.environ.pop("LIVING_GAME_LOOK_WALK", None)
    try:
        out, code, text = drive(run, "look-walk-settings", plan)
    finally:
        if old is not None:
            os.environ["LIVING_GAME_LOOK_WALK"] = old
    c.check(s, "client ran and joined", code == 0, text[-300:])
    L = log(out)
    c.check(s, "Settings › Play › Looking aside › Loose, then Head to 60°, set the preset", "settings: looking aside: loose" in L and "settings: looking aside: head" in L)
    st = os.path.join(out, "settings.json")
    saved = json.load(open(st)).get("look_walk") if os.path.exists(st) else None
    c.check(s, "the settings file keeps it", saved == "head", str(saved))


SCENARIOS = {"windows": windows, "talk": talk, "items": items, "themes": themes, "pick": pick, "turns": turns, "look-walk": look_walk, "support": support}


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
