#!/usr/bin/env python3
"""Run verify-ui scenarios on a verify-ui-* world and check what they did.

  check.py --run RUN [SCENARIO ...]      scenarios: field windows talk items themes film pick turns look-walk bar offers wheel wheel-workplace grid support (default: all but support, wheel-workplace and grid, which need a Cullet world)
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


def drive(run, name, plan, places=(), syncs=(), extra=(), free=()):
    # A run per theme keeps its own evidence (`LIVING_GAME_THEME=night check.py …`).
    name = f"{name}-{THEME}" if THEME else name
    cmd = [sys.executable, os.path.join(HERE, "drive.py"), "--run", run, "--name", name, "--plan", plan, "--timeout", "420"]
    for p in places:
        cmd += ["--place", p]
    for s in syncs:
        cmd += ["--sync", s]
    for p in free:
        cmd += ["--place-free", p]
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
            "sync:hold;wait:0.8;dump:04p;point:{A};wait:0.4;shot:04_hover;key:Enter:tap;wait:0.6;shot:05_to_them;dump:05;type:Hello there, good morning.;enter;wait:0.3;dump:06m1;wait:0.3;dump:06m2;wait:0.3;dump:06m3;wait:0.3;shot:06_said;dump:06;"
            "sync:answer;wait:0.3;dump:06a1;wait:0.3;dump:06a2;wait:0.3;dump:06a3;wait:0.3;shot:06_answer;wait:5.5;dump:06z;"
            "key:Enter:tap;wait:0.4;tab;wait:0.4;dump:07a;tab;wait:0.4;dump:07b;tab;wait:0.4;dump:07c;tab;wait:0.4;dump:07d;tab;wait:0.4;dump:07e;tab;wait:0.4;dump:07f;tab;wait:0.4;dump:07g;tab;wait:0.4;dump:07h;shot:07_tab;key:Escape:tap;wait:0.4;dump:08;"
            "key:KeyL:tap;wait:0.4;click:@log:tab:1;wait:0.4;shot:09_people;click:@log:person:0;wait:0.6;shot:10_window;dump:10;"
            "menu:f@id:{A};wait:0.5;click:@acts:0:window;wait:0.5;click:@person:more;wait:0.5;shot:11_more;dump:11m;click:@acts:0:introduce;wait:0.5;shot:11_intro;dump:11;quit").replace("{A}", str(a))
    # A answers through the speech path minds use (admin `mind_say` for its character: scene
    # setup, not a mind; no model runs in this tier).
    thought = json.dumps({"kind": "talk", "summary": "", "detail": "", "latency_ms": 0, "tokens": 0, "model": "verify-ui scene", "reference": ""})
    answer = f'answer=mind_say|{a}|"Good morning to you, stranger. Fine weather."|{{me}}|""|0|{thought}'
    # On free walkable tiles 1.5-3 m from the player, in sight, across the view (`--place-free`:
    # since fix-place-free `place_at` moves a body off a taken or blocked tile, up to 6 m), and
    # put back there just before the cursor goes to A (town life may walk them off).
    out, code, text = drive(run, s, plan, free=[f"{a}:-2.5:1.0", f"{b}:2.0:-1.0"], syncs=["hold=refree", answer])
    c.check(s, "client ran and joined", code == 0, text[-300:])
    # The scene first: each resident where it landed is 1.5-3 m from me and in view, and they
    # stand apart on screen, before the pick and the Tab checks.
    sc = json.load(open(os.path.join(out, "scene.json"))) if os.path.exists(os.path.join(out, "scene.json")) else {}
    me_at = ((sc.get("placed_at") or {}).get("hold") or {}).get(str(sc.get("me"))) or sc.get("me_at")
    at = (sc.get("placed_at") or {}).get("hold") or sc.get("placed") or {}
    pa, pb = at.get(str(a)), at.get(str(b))
    near = lambda p: p is not None and me_at is not None and 1.4 <= ((p[0] - me_at[0]) ** 2 + (p[1] - me_at[1]) ** 2) ** 0.5 <= 3.1
    seen = {x["id"]: x for x in (dump(out, "04p") or {}).get("seen") or []}
    c.check(s, "scene: both residents are 1.5-3 m from me and in view", near(pa) and near(pb) and a in seen and b in seen, f"me {me_at}, {a} at {pa}, {b} at {pb}, in view {sorted(seen)}")
    apart_m = ((pa[0] - pb[0]) ** 2 + (pa[1] - pb[1]) ** 2) ** 0.5 if pa and pb else 0
    if a in seen and b in seen:
        fa, fb = seen[a]["feet"], seen[b]["feet"]
        ppm = abs(seen[a]["feet"][1] - seen[a]["head"][1]) / 1.75
        apart_px = ((fa[0] - fb[0]) ** 2 + (fa[1] - fb[1]) ** 2) ** 0.5
    else:
        ppm, apart_px = 1, 0
    c.check(s, "scene: the two residents stand at least 1.5 m apart, in the world and on screen", apart_m >= 1.5 and apart_px >= 1.5 * ppm, f"world {apart_m:.2f} m ({pa}, {pb}); screen {apart_px:.0f} px at {ppm:.0f} px/m")
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
    # Up to eight: as many may be within earshot at a busy hour, nearest first, then the room.
    tabs = [(dump(out, f"07{k}") or {}).get("typing") or {} for k in "abcdefgh"]
    # Who is in earshot, as the client has it (nearest first, Tab's order): B among them.
    ear = ((d["06"] or {}).get("typing") or {}).get("earshot") or (tabs[0].get("earshot") if tabs else None) or []
    c.check(s, "who is in earshot: both residents beside me", a in ear and b in ear, f"earshot {ear}")
    # Each Tab against the earshot it went by (`typing.tab` in the dump: whom it came from, the
    # list at that moment, whom it chose), since people walk in and out of earshot between
    # presses at a busy hour: from someone in the list, the next after them, or the room after
    # the last; from the room or someone gone from the list, the first. The press starts where
    # the last one ended; the box then addresses whom it chose (or the room, if they are no
    # longer perceived and so gone from the list too), its window following.
    def nxt(prev, e):
        if not e:
            return prev
        if prev in e:
            i = e.index(prev)
            return e[i + 1] if i + 1 < len(e) else None
        return e[0]
    got = [t.get("to") for t in tabs]
    steps, bad, lists = [], [], []
    for k, t in enumerate(tabs):
        tb = t.get("tab") or {}
        e, prev, chose = tb.get("earshot") or [], tb.get("prev"), tb.get("chose")
        lists.append(e)
        start = a if k == 0 else got[k - 1]
        win = t.get("window") == (f"Person{got[k]}" if got[k] else "Log")
        ok = bool(tb) and prev == start and chose == nxt(prev, e) and (got[k] == chose or (got[k] is None and chose not in (t.get("earshot") or []))) and win
        steps.append(f"{prev}->{got[k]} by {e}")
        if not ok:
            bad.append(k)
    seen_all = [x for e in lists for x in e]
    left = sorted({x for i, e in enumerate(lists) for x in e if any(x not in f for f in lists[i + 1:])})
    # Reaching the room within the presses is required only while earshot held still: someone
    # moving within it or leaving can put the room beyond the eighth press (each press is still
    # checked against its own list above).
    changed = any(e != lists[0] for e in lists) if lists else False
    room = None in got or changed or (lists and min(len(e) for e in lists) >= len(tabs))
    c.check(s, "Tab goes to the next in earshot at each press, nearest first, the window following, then the room", tabs and not bad and room, f"presses {steps}; wrong at {bad}; room reached {None in got}; earshot changed {changed}; left earshot meanwhile {left}; came in {sorted(set(seen_all) - set(ear))}")
    c.check(s, "Esc closes the box and its window", d["08"] and wins(d["08"]) == [] and not d["08"]["typing"], str(wins(d["08"])))
    c.check(s, "Log › People lists them; a click opens a person's window", d["10"] and any(w.startswith("Person") for w, _ in wins(d["10"])), str(wins(d["10"])))
    t11 = (d["11"] or {}).get("typing") or {}
    c.check(s, "their window › More… › Introduce yourself: an editable line to them", t11.get("words", "").startswith("I'm Verifier") and t11.get("to") == a and t11.get("window") == f"Person{a}", json.dumps(t11))
    # Mouths (`mouth.rs`): mine moves while my line is said, A's while their answer is, and both
    # are shut once the words are said (the dumps' `extra.mouths`, by character id).
    me = (json.load(open(os.path.join(out, "scene.json"))) if os.path.exists(os.path.join(out, "scene.json")) else {}).get("me")
    mouth = lambda k, who: ((((dump(out, k) or {}).get("extra") or {}).get("mouths")) or {}).get(str(who))
    mine = [mouth(k, me) for k in ("06m1", "06m2", "06m3")]
    c.check(s, "my mouth moves while my line is said", me is not None and any((w or 0) > 0.05 for w in mine), str(mine))
    called = [x for x in sc.get("calls", []) if x.get("reducer") == "mind_say"]
    theirs = [mouth(k, a) for k in ("06a1", "06a2", "06a3")]
    c.check(s, "their mouth moves while their answer is said (their line through mind_say)", called and called[0].get("code") == 0 and any((w or 0) > 0.05 for w in theirs), f"{theirs}; {called[:1]}")
    late = (((dump(out, "06z") or {}).get("extra") or {}).get("mouths") or {})
    c.check(s, "and both mouths are shut once the words are said", not any((late.get(str(i)) or 0) > 0 for i in (me, a)), json.dumps(late))
    rows = sql(run, f"SELECT kind, object, text FROM experience WHERE kind = 'said' AND object = {a}")
    c.check(s, "the authority's said row has to = the addressee", any("Hello there, good morning." in r.get("text", "") for r in rows), f"{len(rows)} said rows to #{a}")
    rows0 = sql(run, "SELECT kind, object, text FROM experience WHERE kind = 'said' AND object = 0")
    c.check(s, "and the room's line has to = 0", any("Good morning, all." in r.get("text", "") for r in rows0), f"{len(rows0)} said rows to the room")
    more = ((dump(out, "11m") or {}).get("acts") or {}).get("rows") or []
    c.check(s, "every act toward them (More…) leaves out face: a player faces where it looks (play-test 5)", len(more) > 3 and not any(r == "face" or r.startswith("face ") for r in more), str(more))


def items(run, c):
    s = "items"
    a, b = residents(run)
    # The gives are proven by their outcomes, not by the receiver's berries: a resident is free
    # until the scene holds it (sync:scene, once the client is ready) and eats, gathers and gives
    # berries meanwhile, so a count taken before the drive is no baseline (verify-player's rule).
    t0 = int(time.time() * 1000) - 1000
    plan = ("ready;sync:scene;sync:kit;wait:1.5;menu:f@id:{A};wait:0.5;click:@acts:0:window;wait:0.6;dump:01;key:KeyI:tap;wait:0.6;shot:01_pack_person;dump:02;"
            "click:@pack:berries;wait:0.5;shot:02_item_acts;dump:03;key:Escape:tap;wait:0.3;slide:@pack:berries>@win:Person{A}:head:0.8;wait:2;shot:03_dropped;dump:04;"
            "menu:f@id:{A};wait:0.5;shot:04_hold_f;dump:05;click:@acts:0:give;wait:0.5;shot:05_give_sub;dump:06;click:@acts:1:berries;wait:2;shot:06_given;dump:07;sync:load;wait:2;shot:07_load;dump:08;quit").replace("{A}", str(a))
    # The newcomer's berries may be gone from earlier runs: the scene grants four (admin).
    # Then a basket (room 20) and ten arrows (0.1 each) for the pack's load and limit (goods-3).
    load = 'load=grant_items|{me}|"basket"|1;grant_items|{me}|"arrow"|10'
    out, code, text = drive(run, s, plan, places=[f"{a}:-2.5:2.0", f"{b}:-1.0:3.2"], syncs=['kit=grant_items|{me}|"berries"|4', load])
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
    p7, p8 = (dump(out, "07") or {}).get("pack") or {}, (dump(out, "08") or {}).get("pack") or {}
    dl = (p8.get("limit") or 0) - (p7.get("limit") or 0)
    dc = (p8.get("carried") or 0) - (p7.get("carried") or 0)
    had = dict(map(tuple, p7.get("items") or [])).get("basket", 0)
    # The first basket adds its room (20); another adds nothing (the largest room, not a sum).
    want = 0.0 if had else 20.0
    c.check(s, f"the pack's limit adds the largest room carried (a basket: {want:.0f} more, {had} carried before)", p7 and p8 and abs(dl - want) < 1e-3, f"limit {p7.get('limit')} -> {p8.get('limit')}")
    c.check(s, "its load counts each item by its carry (ten arrows at 0.1, a basket)", p7 and p8 and 1.0 - 1e-3 <= dc < 10.0, f"carried {p7.get('carried')} -> {p8.get('carried')}")


THEMES = ["glass", "clear", "night", "linen", "walnut"]  # F4's order (`ui::wood::Name::ALL`)



def themes(run, c):
    s = "themes"
    n = len(THEMES)
    # A fresh settings file and no LIVING_GAME_THEME: the client starts in the default, Glass.
    if not THEME:
        out0 = os.path.join(ROOT, ".local/living/verify", run, "ui", "themes-default")
        st0 = os.path.join(out0, "settings.json")
        if os.path.exists(st0):
            os.remove(st0)
        out0, code0, text0 = drive(run, "themes-default", "ready;wait:2;key:KeyI:tap;wait:0.5;dump:01;shot:01_default;quit")
        c.check(s, "a fresh settings file starts in Glass", ((dump(out0, "01") or {}).get("extra") or {}).get("theme") == "glass", str(((dump(out0, "01") or {}).get("extra") or {}).get("theme")))
    keys = [f"{i + 1:02d}" for i in range(n)]
    steps = ";".join(f"key:F4:tap;wait:0.8;shot:{k}_next;dump:{k}" for k in keys[1:])
    plan = (f"ready;wait:2;key:KeyL:tap;wait:0.3;key:KeyI:tap;wait:0.5;dump:01;shot:01_first;{steps};"
            f"click:@menu;wait:0.3;click:@menu:Settings;wait:0.6;click:@settings:theme:linen;wait:0.8;shot:{n + 1:02d}_linen;dump:{n + 1:02d};quit")
    out, code, text = drive(run, s, plan)
    c.check(s, "client ran and joined", code == 0, text[-300:])
    d = {k: dump(out, k) for k in keys + [f"{n + 1:02d}"]}
    names = [((d[k] or {}).get("extra") or {}).get("theme") for k in keys]
    first = names[0]
    want = [THEMES[(THEMES.index(first) + i) % n] for i in range(n)] if first in THEMES else []
    c.check(s, "F4 cycles every theme in order", names == want, str(names))
    c.check(s, "each change is named on screen", len(re.findall(r"ui: Theme: \w+  ·  F4 changes it", log(out))) >= n - 1)
    c.check(s, "windows stay where they were through a change", all(sorted(wins(d[k])) == [("Log", "Left"), ("Pack", "Right")] for k in keys), str([wins(d[k]) for k in keys]))
    c.check(s, "Settings › Play › Look sets it", ((d[f"{n + 1:02d}"] or {}).get("extra") or {}).get("theme") == "linen")
    st = os.path.join(out, "settings.json")
    saved = json.load(open(st)).get("theme") if os.path.exists(st) else None
    c.check(s, "the settings file keeps it", saved == "linen", str(saved))


def film(run, c):
    """The film (`post::Film`, Settings › Play › Film): a fresh settings file starts in Soft and
    saves no choice; Settings sets Full and None and the file keeps the last; the next start reads
    it back. Stills of the three modes from one place (`01_soft`, `03_screen`, `04_off`), the
    unseen ground's edge in view, for the eye. `LIVING_GAME_FILM` must not be set."""
    s = "film"
    if os.environ.get("LIVING_GAME_FILM"):
        c.check(s, "LIVING_GAME_FILM is unset (it overrides the settings file)", False, os.environ["LIVING_GAME_FILM"])
        return
    out0 = os.path.join(ROOT, ".local/living/verify", run, "ui", "film")
    st = os.path.join(out0, "settings.json")
    if os.path.exists(st):
        os.remove(st)
    open_settings = "click:@menu;wait:0.4;click:@menu:Settings;wait:0.6;"
    plan = ("ready;wait:3;dump:01;shot:01_soft;" + open_settings + "click:@settings:film:screen;wait:0.4;dump:02;shot:02_settings;key:Escape:tap;wait:0.8;dump:03;shot:03_screen;"
            + open_settings + "click:@settings:film:off;wait:0.4;key:Escape:tap;wait:0.8;dump:04;shot:04_off;" + open_settings + "click:@settings:film:screen;wait:0.6;quit")
    out, code, text = drive(run, s, plan)
    c.check(s, "client ran and joined", code == 0, text[-300:])
    x = lambda k: ((dump(out, k) or {}).get("extra") or {})
    c.check(s, "a fresh settings file starts in Soft and saves no choice", x("01").get("film") == "soft" and x("01").get("film_saved") is None, str((x("01").get("film"), x("01").get("film_saved"))))
    c.check(s, "Settings › Play › Film › Full sets the screen film", x("02").get("film") == "screen" and x("03").get("film") == "screen", str((x("02").get("film"), x("03").get("film"))))
    c.check(s, "None turns it off", x("04").get("film") == "off", str(x("04").get("film")))
    c.check(s, "the log names each choice", log(out).count("settings: film: ") == 3)
    saved = json.load(open(st)).get("film") if os.path.exists(st) else None
    c.check(s, "the settings file keeps the last choice", saved == "screen", str(saved))
    out2, code2, _ = drive(run, s, "ready;wait:2;dump:05;quit")
    c.check(s, "the next start reads it back", (((dump(out2, "05") or {}).get("extra") or {}).get("film")) == "screen", str(((dump(out2, "05") or {}).get("extra") or {}).get("film")))


def act(actor, a):
    """An admin `mind_act` for a resident, as its mind would decide (scene setup)."""
    inner = json.dumps(a, separators=(",", ":")).replace('"{me}"', "{me}")  # the player's id, filled in by drive.py
    return "mind_act|%d|%s|\"verify-ui\"" % (actor, json.dumps([inner]))


def offers(run, c):
    """A resident's swap and terms, offered to the player (admin `mind_act`, as a mind decides):
    each a card in the maker's window; its buttons are the rules' skills on `offer` (Accept,
    Decline), naming the card's offer or record; a refusal is the rules' words; Decline tells the
    maker. It leaves nothing standing; one left by a failed run opens its maker's window on
    arrival until it lapses (`trade_window_s`)."""
    s = "offers"
    a, b = residents(run)
    inv = lambda who, item: sum(r["qty"] for r in sql(run, f"SELECT item, qty FROM inventory WHERE owner = {who} AND item = '{item}'"))
    ME = "{me}"
    swap = act(a, {"do": "offer", "target": {"id": ME}, "item": "berries", "qty": 2, "want": "wood", "want_qty": 1})
    dear = act(a, {"do": "offer", "target": {"id": ME}, "item": "berries", "qty": 2, "want": "hide", "want_qty": 5})
    terms = act(b, {"do": "offer_terms", "target": {"id": ME}, "item": "berries", "qty": 1, "want": "stone", "want_qty": 1, "text": "bring it by dusk"})
    plan = ("ready;sync:scene;sync:kit;wait:1;sync:swap;wait:4;shot:01_offer;dump:01;click:@person:offer:{A}:0:0;wait:4;shot:02_taken;dump:02;"
            "sync:dear;wait:4;dump:03;click:@person:offer:{A}:0:0;wait:4;shot:03_refused;dump:04;click:@person:offer:{A}:0:1;wait:4;shot:04_declined;dump:05;"
            "sync:again;wait:4;dump:07;click:@person:offer:{A}:0:0;wait:4;dump:08;"
            "sync:terms;wait:4;shot:05_terms;dump:06;key:Escape:tap;wait:0.4;menu:f@id:{B};wait:0.5;click:@acts:0:window;wait:0.8;shot:06_terms_card;dump:09;"
            "click:@person:offer:{B}:0:0;wait:4;shot:07_agreed;dump:10;"
            "menu:f@id:{B};wait:0.5;click:@acts:0:offer;wait:0.5;dump:11a;click:@acts:1:berries;wait:0.5;click:@acts:1:berries_for_wood;wait:3;menu:f@id:{B};wait:0.5;click:@acts:0:window;wait:0.8;shot:08_mine;dump:11;quit").replace("{A}", str(a)).replace("{B}", str(b))
    # Goods for the swaps and the terms (admin), then the residents' own acts.
    kit = f'kit=grant_items|{a}|"berries"|4;grant_items|{b}|"berries"|1;grant_items|{{me}}|"wood"|1'
    # Offered again, with the wood for it: the scene leaves nothing standing.
    again = f'grant_items|{{me}}|"wood"|1;{swap}'
    wood0 = inv(a, "wood")
    # Within reach (3 m: the rules refuse an accept from farther, "Out of reach").
    out, code, text = drive(run, s, plan, places=[f"{a}:-1.8:1.2", f"{b}:-0.6:2.2"], syncs=[kit, f"swap={swap}", f"dear={dear}", f"again={again}", f"terms={terms}"])
    c.check(s, "client ran and joined", code == 0, text[-300:])
    d = {k: dump(out, k) for k in ["01", "02", "03", "04", "05", "06", "07", "08", "09", "10", "11"]}
    cards = lambda k: ((d[k] or {}).get("extra") or {}).get("cards") or []
    tags = lambda k: set(((d[k] or {}).get("tags") or {}).keys())
    notes = lambda k: (d[k] or {}).get("notes") or []
    # A card per standing proposal: its acts are the rules' skills on `offer` (Accept, Decline).
    acc, dec = f"person:offer:{a}:0:0", f"person:offer:{a}:0:1"
    c.check(s, "an offer opens their window with Accept and Decline", (f"Person{a}", "Left") in wins(d["01"]) and {acc, dec} <= tags("01"), str((wins(d["01"]), sorted(tags("01")))))
    left = [cd["text"] for cd in cards("01") if cd["with"] == a]
    secs = [int(m.group(1)) * 60 + int(m.group(2)) for t in left for m in [re.search(r"(\d+):(\d\d) left", t)] if m]
    c.check(s, "the card counts down to until_ms (at most the 3 min window)", secs and 0 < secs[0] <= 180, str(left))
    c.check(s, "the note says the offer in the rows' goods", any("offers you 2 berries for 1 wood" in n for n in notes("01")), str(notes("01")))
    L = log(out)
    sent = len(re.findall(rf'"do":"accept","offer":\d+,"target":\{{"id":{a}\}}', L))
    c.check(s, "Accept sends the rules' accept toward its maker, naming the offer (human_act)", sent >= 1, f"{sent} sent")
    c.check(s, "the card's button is the rules' skill on `offer`, by its label", re.search(rf'verbs: Accept → \{{"do":"accept"', L) is not None)
    c.check(s, "the card goes when the rules take the offer", acc not in tags("02"), str(sorted(tags("02"))))
    me = json.load(open(os.path.join(out, "scene.json"))).get("me")
    c.check(s, "the rules traded it (their note: 2 berries for 1 wood)", any("2 berries for 1 wood" in n for n in notes("02")), str(notes("02")))
    # Both swaps they made took a wood of mine.
    c.check(s, "the authority swapped the goods (they got my wood, twice)", inv(a, "wood") - wood0 == 2, f"their wood {wood0} -> {inv(a, 'wood')}")
    c.check(s, "a second offer shows again", acc in tags("03"), str(sorted(tags("03"))))
    c.check(s, "a refused accept is noted in the rules' words and the card stays", acc in tags("04") and len(notes("04")) > len([n for n in notes("03") if n in notes("04")]), str(notes("04")))
    c.check(s, "Decline sends the rules' decline, naming the offer", re.search(rf'verbs: Decline → \{{"do":"decline","offer":\d+,"target":\{{"id":{a}\}}', L) is not None)
    c.check(s, "and the card closes (the rules drop the offer)", acc not in tags("05"), str(sorted(tags("05"))))
    told = [r for r in sql(run, f"SELECT kind, text FROM experience WHERE observer = {a}") if "declined your offer" in r.get("text", "")]
    c.check(s, "the maker is told (\"… declined your offer …\")", len(told) >= 1, str([r.get("text") for r in told][-2:]))
    c.check(s, "proposed terms are noted once, in the rules' words", len([n for n in notes("06") if "bring it by dusk" in n]) == 1, str(notes("06")))
    c.check(s, "offered again, it shows again", acc in tags("07"), str(sorted(tags("07"))))
    c.check(s, "and taken, it goes", acc not in tags("08"), str(sorted(tags("08"))))
    tb = f"person:offer:{b}:0:0"
    c.check(s, "the terms have their own card in the proposer's window", tb in tags("09") and (f"Person{b}", "Left") in wins(d["09"]), str((wins(d["09"]), sorted(t for t in tags("09") if t.startswith("person:")))))
    c.check(s, "Accept on it names the record", re.search(rf'verbs: Accept → \{{"do":"accept","record":\d+,"target":\{{"id":{b}\}}', L) is not None)
    c.check(s, "Accept on it agrees to the terms (the record is agreed) and the card goes", tb not in tags("10") and any(r.get("status") == "agreed" for r in sql(run, f"SELECT status FROM record WHERE kind = 'agreement'")), str(sql(run, "SELECT status FROM record WHERE kind = 'agreement'")))
    mine = [cd["text"] for cd in cards("11") if cd["with"] == b]
    c.check(s, "my own offer (Offer › berries) shows in their window, counting down, with no answers", any(t.startswith("You offer") and "left" in t for t in mine) and f"person:offer:{b}:0:0" not in tags("11"), str((mine, sorted(t for t in tags("11") if t.startswith("person:offer")))))
    c.check(s, "nothing is left standing toward me", me is not None and sql(run, f"SELECT id FROM trade_offer WHERE to = {me}") == [], str(sql(run, f"SELECT * FROM trade_offer WHERE to = {me}") if me else "?"))
    c.check(s, "and the client reads them as terms (Accept takes them)", re.search(rf"ui: proposal Terms\(\d+\) from #{b}: .*proposes terms: they give 1 berries, you give 1 stone", L) is not None)

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
            "point:{A}:1.3;wait:0.8;tap;wait:0.8;dump:04;key:Escape:tap;wait:0.4;"
            "sync:stack;wait:1;point:{A}:1.0;wait:0.5;dump:05a;wait:0.5;dump:05b;wait:0.5;dump:05c;shot:05_stacked;quit").replace("{A}", str(a)).replace("{LINE}", line)
    # Last, both on one spot (stacked exactly on screen): one answer every frame, the nearer the camera.
    stack = f"stack=place_at|{a}|(mx-3.0)|(my-1.0);place_at|{b}|(mx-3.0)|(my-1.0)"
    out, code, text = drive(run, s, plan, places=[f"{a}:-3.0:-1.0", f"{b}:-3.0:-2.5"], syncs=[stack])
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
    # Both asked for one spot: `place_at` keeps bodies on free tiles (fix-place-free), so the
    # second lands on a neighbouring one and their outlines overlap on screen. The pick holds one
    # every frame: the nearest the camera of those whose outline holds the cursor, by the
    # client's own test (`holds` in the dump; exact ties are pick.rs's unit test).
    st = [dump(out, f"05{k}") or {} for k in "abc"]
    unders = [x.get("under") for x in st]
    def front(x):
        held = [b_ for b_ in (x.get("seen") or []) if b_.get("holds")]
        return min(held, key=lambda b_: (b_["depth"], b_["id"]))["id"] if held else None
    c.check(s, "two bodies asked onto one spot, overlapping on screen: the same one every frame, the nearest the camera under the cursor", len(set(unders)) == 1 and unders[0] in (a, b) and all(front(x) == unders[0] for x in st), f"under {unders}, front of those under the cursor {[front(x) for x in st]}")


def bar(run, c):
    """The cluster on the rules' bar (`bar_places`): sheathed, the hostile slots are greyed with
    their reason and X draws; a press the rules refuse is noted in their words and flashes its
    slot; a held guard shows held; the tooltip names the slot and why it is greyed."""
    s = "bar"
    plan = ("ready;wait:2;cursor:0.5,0.3;wait:0.3;shot:01_sheathed;dump:01;cursor:@bar:Primary;wait:0.5;shot:02_tip;dump:02;"
            "cursor:0.5,0.3;key:KeyX:tap;wait:0.6;shot:03_drawn;dump:03;cursor:0.5,0.06;wait:0.3;tap;wait:0.4;shot:04_refused;dump:04;wait:0.6;cursor:0.5,0.3;"
            "key:KeyQ:down;wait:0.5;shot:05_block;dump:05;key:KeyQ:up;wait:0.3;key:KeyX:tap;wait:0.5;dump:06;quit")
    out, code, text = drive(run, s, plan)
    c.check(s, "client ran and joined", code == 0, text[-300:])
    d = {k: dump(out, k) for k in ["01", "02", "03", "04", "05", "06"]}
    ex = lambda k: (d[k] or {}).get("extra") or {}
    slot = lambda k, n: (ex(k).get("slots") or {}).get(f"bar:{n}") or {}
    L = log(out)
    m = re.search(r"combat: bar places primary Some\(\"(\w+)\"\), secondary Some\(\"(\w+)\"\), keys \[([^\]]*)\], jump Some\(\"(\w+)\"\), dodge Some\(\"(\w+)\"\)", L)
    c.check(s, "the bar is the rules' bar_places (strike, bow shot; block, heal, fire bolt; jump; dodge)", m is not None and m.group(1, 2, 4, 5) == ("strike", "bowshot", "jump", "dodge") and "block" in m.group(3) and "firebolt" in m.group(3), m.group(0) if m else "no bar places logged")
    c.check(s, "the slots carry the declared labels", (slot("01", "Primary").get("label"), slot("01", "Secondary").get("label"), slot("01", "Skill3").get("label")) == ("Strike", "Bow shot", "Fire bolt"), str([slot("01", n).get("label") for n in ["Primary", "Secondary", "Skill3"]]))
    c.check(s, "sheathed at first, and the weapon slot says so", ex("01").get("drawn") is False and slot("01", "Weapon").get("caption") == "sheathed", str((ex("01").get("drawn"), slot("01", "Weapon"))))
    c.check(s, "sheathed, the hostile slots are greyed with the reason", "Sheathed" in (slot("01", "Primary").get("off") or "") and "Sheathed" in (slot("01", "Secondary").get("off") or ""), str((slot("01", "Primary").get("off"), slot("01", "Secondary").get("off"))))
    c.check(s, "a guard or a heal is not greyed by the sheath", "Sheathed" not in (slot("01", "Skill1").get("off") or "") and "Sheathed" not in (slot("01", "Skill2").get("off") or ""), str((slot("01", "Skill1").get("off"), slot("01", "Skill2").get("off"))))
    tip = ex("02").get("tooltip") or {}
    c.check(s, "hovering a slot shows its label and why it is greyed", tip.get("title") == "Strike" and "X draws" in (tip.get("text") or ""), str(tip))
    c.check(s, "X draws the weapon", ex("03").get("drawn") is True and slot("03", "Weapon").get("caption") == "drawn" and not slot("03", "Primary").get("off"), str((ex("03").get("drawn"), slot("03", "Primary"))))
    notes = (d["04"] or {}).get("notes") or []
    c.check(s, "a strike at no one is refused, in the rules' words, on the slot and as a note", slot("04", "Primary").get("refused") is True and len(notes) > 0, str((slot("04", "Primary"), notes)))
    c.check(s, "Q held raises the guard: its slot shows held", slot("05", "Skill1").get("held") is True, str(slot("05", "Skill1")))
    c.check(s, "X again sheathes it", ex("06").get("drawn") is False, str(ex("06").get("drawn")))
    # The bars and pills from the world's rules: `meters()` (the shown ones, in order) and
    # `status_of` (a plain status is the body's words when all is well: no pill).
    me = (d["01"] or {}).get("me") or {}
    ms = me.get("meters") or []
    # The shipped script (stamina-1): health and stamina shown; focus ("Mana") only while short;
    # energy and hunger feed the statuses off the screen.
    names = [m["name"] for m in ms]
    c.check(s, "the bars are the world's shown meters (health, stamina; mana only while short), each within its max", names[:2] == ["health", "stamina"] and not ({"energy", "hunger"} & set(names)) and all(0 <= m["value"] <= m["max"] + 1e-3 and m["label"] for m in ms) and all(m["value"] < m["max"] for m in ms if m["name"] == "focus"), str(ms))
    c.check(s, "the pills are the rules' statuses, none plain", all(x["tone"] != "Plain" for x in me.get("statuses") or []), str(me.get("statuses")))


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
    """The authority's heading_at on a body row (the travel heading)."""
    if not b.get("turn") or b.get("turn_s", 0) <= 0:
        return wrap(b["heading"])
    t = max(0, min(now_ms, b["next_ms"]) - b["t_ms"]) / 1000.0
    return wrap(b["heading"] + b["turn"] * min(t, b["turn_s"]))


def facing_at(b, now_ms):
    """The authority's facing_at: the travel heading plus the facing offset (look-2's
    `face_off`, eased by `face_turn` over `face_turn_s`), the one facing sight reads."""
    t = max(0, min(now_ms, b["next_ms"]) - b["t_ms"]) / 1000.0
    off = b.get("face_off") or 0.0
    if b.get("face_turn") and (b.get("face_turn_s") or 0) > 0:
        off += b["face_turn"] * min(max(t, 0.0), b["face_turn_s"])
    return wrap(heading_at(b, now_ms) + off)


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
# Where the field scene stands the player first (open grass west of Brackenford on the island
# seed, look-walk's spot), so every run starts alike: a re-run used to start where the last one
# left the character, often with a building north of it, and the walk was steered or blocked.
FIELD_SPOT = (300.0, 330.0)
# The walk goes north-west (compass), between the residents placed north and west, not at one.
FIELD_WALK = 315
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
    h_auth = facing_at(mine, at)
    eye = (mine["x"], mine["y"])
    out = {"heading_client": math.degrees(fc["heading"]), "heading_authority": math.degrees(h_auth), "dump": meta["n"], "same": [], "differ": [], "margin": [], "moving": []}
    for bid, b in bodies.items():
        if bid == me:
            continue
        # A body under way: its row is where its segment began, not where it is now, and the
        # authority's sweep saw it somewhere between. Standing bodies only are compared.
        if b.get("next_ms", 0) < (1 << 63):
            out["moving"].append(bid)
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
    perceived set matches the client's field; walking (north-west from a fixed open spot), the look
    is released, or with FACE_WHILE_MOVING held at `look_walk_deg` off the travel; a release
    brings the facing back to the travel and leaves a standing body facing where it was; the
    Settings switch turns it off again; each switch is a law_change row."""
    s = "field"
    ids = residents(run, len(FOV_PLACES))
    if len(ids) < len(FOV_PLACES):
        c.check(s, f"{len(FOV_PLACES)} residents to place", False, f"only {ids}")
        return
    # Off at the start: the law as shipped (a re-run starts from it again).
    subprocess.run([sys.executable, V, "call", "--run", run, "--as-admin", "set_world_law", '["fov_on", "false"]'], capture_output=True, text=True)
    changes0 = sql(run, "SELECT id FROM law_change")
    snap = lambda n: f"{n}=sql|SELECT id, x, y, heading, turn, turn_s, t_ms, next_ms, face_off, face_turn, face_turn_s FROM body;sql|SELECT body FROM perceived WHERE viewer = 0x{{ident}};sql|SELECT key, target, bearing, band FROM heard WHERE listener = {{me}}"
    body = lambda n: f"{n}=sql|SELECT id, x, y, heading, turn, turn_s, t_ms, next_ms, vx, vy, face_off, face_turn, face_turn_s FROM body WHERE id = {{me}}"
    # By day (`{epoch_at:12}`, a scratch fixture): at night side vision is left out of the
    # comparison for the lights the client can't know, and a day lasts 12 minutes.
    plan = "ready;frame:0;yaw:0;sync:spot;wait:5;sync:noon;sync:scene;wait:2;dump:01_off;shot:01_off;key:F5:tap;wait:2.5;dump:02_on;shot:02_on;sync:senses"
    # A look the other way first: a look within `look_slack_deg` (10°) of where a standing body
    # already faces writes nothing (a re-run's character may already face about north), so the
    # first look turns the body as every other does.
    plan += f";look:{(FOV_LOOKS[0] + 180) % 360};wait:2"
    for deg in FOV_LOOKS:
        plan += f";look:{deg};wait:2.5;sync:h{deg};dump:h{deg};shot:h{deg}"
    # Walking north-west with the look east (135° off the travel): held at look_walk_deg; F3 (to
    # "where you walk") releases it while walking, then standing.
    plan += (f";look:90;hold:{FIELD_WALK};wait:2;sync:walk;key:F3:tap;wait:1.5;sync:released;stop;wait:1.5;key:F3:tap;look:270;wait:2;sync:looked;key:F3:tap;wait:1.5;sync:stood;"
             "click:@menu;wait:0.4;click:@menu:Settings;wait:0.8;shot:03_settings_on;dump:03;click:@settings:facing_sight;wait:2.5;shot:04_settings_off;dump:04;quit")
    syncs = [f"spot=place_at|{{me}}|{FIELD_SPOT[0]}|{FIELD_SPOT[1]}", "noon=sql|UPDATE world SET epoch_ms = {epoch_at:12} WHERE id = 0", "senses=sql|SELECT * FROM character_senses WHERE id = {me}"] + [snap(f"h{d}") for d in FOV_LOOKS] + [body(n) for n in ("walk", "released", "looked", "stood")]
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
    note = ((d["02_on"] or {}).get("extra") or {}).get("facing_note") or ""
    pill = "facing:pill" in ((d["02_on"] or {}).get("tags") or {}) or note.startswith("Facing sight on")
    c.check(s, "…on screen as a short note at the top (not over my character), the values off the play view", note.startswith("Facing sight on") and pill and not any(t.startswith("Focal ±") for t in toasts), f"note {note!r}; toasts {toasts}")
    sc = json.load(open(os.path.join(out, "scene.json"))) if os.path.exists(os.path.join(out, "scene.json")) else {}
    me = sc.get("me")
    snaps = sc.get("snaps") or {}
    # The client's senses are the authority's own (`my_senses`, owner SQL on `character_senses`).
    row = ((snaps.get("senses") or [{}])[0].get("rows") or [None])[0]
    keys = ["focal_deg", "side_deg", "side_share", "near_m", "margin_deg"]
    same = row is not None and row.get("field") is True and on.get("source") == "Authority" and abs((on.get("sight") or -1) - row["sight"]) < 1e-3 and all(abs(fv.get(k, -1) - row[k]) < 1e-3 for k in keys)
    c.check(s, "after F5 the client's sight and five values are my_senses' (the authority's row)", same, f"client {json.dumps(on)}; my_senses {json.dumps(row)}")
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
    look = 0.0  # the look east (sim degrees), held through the walk
    # Judged against the authority's own travel, not the keys' way: steering may bend a walk
    # round someone or slide it along a wall, and the look is about the facing against the travel.
    # FACE_WHILE_MOVING off: the client releases its look while a direction is held, so the facing
    # is the travel. On (look-3, with look-2's authority): the facing turns toward the look, at
    # most look_walk_deg (75°) off the travel.
    face_moving = re.search(r"pub const FACE_WHILE_MOVING: bool = (\w+);", open(os.path.join(ROOT, "living/game/src/controls.rs")).read())
    face_moving = face_moving and face_moving.group(1) == "true"

    def travel_of(row, at):
        """The travel (degrees): the velocity's way when moving, else the travel heading."""
        if math.hypot(row["vx"], row["vy"]) > 0.5:
            return math.degrees(math.atan2(row["vy"], row["vx"]))
        return math.degrees(heading_at(row, at))

    def off(a, b):
        return math.degrees(wrap(math.radians(a - b)))

    if walk:
        at = snaps["walk"][0]["wall_ms"]
        f, t = math.degrees(facing_at(walk, at)), travel_of(walk, at)
        speed = math.hypot(walk["vx"], walk["vy"])
        keys = math.degrees(wrap(math.radians(FIELD_WALK - 90)))
        c.check(s, "the walk under way (north-west, the scene's open way)", speed > 0.5 and abs(off(t, keys)) < 30.0, f"travel {t:.1f}° (keys {keys:.1f}°), speed {speed:.2f}")
        if face_moving:
            want = math.copysign(min(75.0, abs(off(look, t))), off(look, t))
            c.check(s, "walking with the look 135° off: the facing turns 75° toward it, not more (look_walk_deg)", abs(off(f, t) - want) < 4.0, f"facing {f:.1f}°, travel {t:.1f}°: {off(f, t):+.1f}° (want {want:+.1f}°)")
        else:
            c.check(s, "walking with the cursor east: the look is released while moving, the body faces its travel", abs(off(f, t)) < 4.0, f"facing {f:.1f}°, travel {t:.1f}°")
        moving_rel = re.search(r"look: human_face\(0\.000, 0\.000\)", L) is not None
        c.check(s, "…the release went as human_face(0, 0)", moving_rel or face_moving)
    if rel:
        at = snaps["released"][0]["wall_ms"]
        f, t = math.degrees(facing_at(rel, at)), travel_of(rel, at)
        c.check(s, "a release while walking brings the facing back to the travel", abs(off(f, t)) < 4.0, f"facing {f:.1f}°, travel {t:.1f}°")
    if looked and stood:
        h1 = math.degrees(facing_at(looked, snaps["looked"][0]["wall_ms"]))
        h2 = math.degrees(facing_at(stood, snaps["stood"][0]["wall_ms"]))
        c.check(s, "standing, a look west turns the body there and a release leaves it there", abs(abs(h1) - 180.0) < 4.0 and abs(math.degrees(wrap(math.radians(h2 - h1)))) < 2.0, f"looked {h1:.1f}°, after the release {h2:.1f}°")
    sends = len(re.findall(r"look: human_face\(", L))
    refusals = re.findall(r"(?:look|face) refused: ([^\n]+)", L)
    c.check(s, "looks went through human_face, none refused for anything but the input bucket", sends >= 6 and all("too many movement inputs" in x for x in refusals), f"{sends} sends; refusals {refusals[:3]}")
    c.check(s, "Settings › Play shows facing sight on, its switch and the values", fs("03").get("on") and "settings:facing_sight" in ((d["03"] or {}).get("tags") or {}))
    c.check(s, "the Settings switch turns it off; the field goes", fs("04").get("on") is False and dumps and dumps[-1][0].get("facing") is None, json.dumps(fs("04")))
    c.check(s, "…and the readout says so", re.search(r"facing: Facing sight off", L) is not None)
    changes = sql(run, "SELECT id, name, old, new, revision FROM law_change")
    new = [r for r in changes if r["id"] not in {x["id"] for x in changes0}]
    c.check(s, "each switch is a law_change row (fov_on false → true → false)", [(r["name"], r["new"]) for r in sorted(new, key=lambda r: r["id"])] == [("fov_on", "true"), ("fov_on", "false")], str(new))


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
    env_keep = {k: os.environ.get(k) for k in ["LIVING_GAME_FEET", "LIVING_GAME_CONTROL", "LIVING_GAME_RECORD", "LIVING_GAME_LOOK_WALK"]}
    os.environ["LIVING_GAME_FEET"] = os.path.join(out_dir, "feet.jsonl")
    # The preset from the first frame: the character's row may still hold a facing from the last
    # drive (a look stays held on the authority when a client quits), which the body draws.
    os.environ["LIVING_GAME_LOOK_WALK"] = preset
    os.environ["LIVING_GAME_CONTROL"] = "cursor"
    if os.environ.get("LOOK_WALK_RECORD"):
        os.environ["LIVING_GAME_RECORD"] = os.path.join(out_dir, "record")
    try:
        if os.environ.get("LOOK_WALK_REUSE") and os.path.exists(os.path.join(out_dir, "feet.jsonl")):
            # Check the last drive's log again (iterating on the checks).
            out, code, text = out_dir, 0, "reused"
        else:
            out, code, text = drive(run, name, plan, syncs=[f"spot=place_at|{{me}}|{LOOK_WALK_SPOT[0]}|{LOOK_WALK_SPOT[1]}"], extra=["--token", os.environ["LOOK_WALK_TOKEN"]] if os.environ.get("LOOK_WALK_TOKEN") else ())
    finally:
        for k, v in env_keep.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    c.check(s, "client ran and joined", code == 0, text[-300:])
    rows = feet_log(out)
    # Only the scenario's own frames: from its first scripted look (after the spot and the preset
    # are set). Before that the body stands wherever the last drive left it, and the first-time
    # tip's click can strike; since fov-client, `human_face` turns a standing body to the
    # cursor, so those frames turn and twist for reasons this scenario doesn't set up.
    first = next((i for i, r in enumerate(rows) if r.get("look") is not None), len(rows))
    rows = rows[first:]
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
        # The feet test counts only while the legs are turned off the travel (or its reverse)
        # by more than 15°: square on it, a forward or back gait is the clip's own stride, and a
        # run puts its feet near one line (its ankles overlap up to 4–9 cm with the look straight
        # ahead too: `run` at the 2.8 m/s walk/run boundary, `run_fast` on a road). Those frames
        # are counted apart (`own_overlap` in look_walk.json).
        off = abs(r["legs_off"]) if r["legs_off"] is not None else 0.0
        r["aside"] = min(off, 180.0 - off) > 15.0
        r["crossed"] = r["cross_w"] > 0.25 or (r["aside"] and r["sep"] is not None and r["sep"] < -0.03)
        r["own_overlap"] = not r["aside"] and r["sep"] is not None and r["sep"] < -0.03
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
    # A frame may turn the legs more than 15° only within 720°/s (`live.rs` TURN_MAX; the body's
    # own cap is lower) over a long frame.
    jumps = [(abs(wrapd(rows[i]["yaw"] - rows[i - 1]["yaw"])), rows[i]["dt"]) for i in range(1, len(rows)) if 0 < rows[i]["dt"] <= 0.05]
    bad = [(d, dt) for d, dt in jumps if d > max(15.0, 720.0 * dt + 1.0)]
    hitches = sum(1 for r in rows if r["dt"] > 0.05)
    worst = max(jumps or [(0, 0)])
    c.check(s, "the legs come round eased: no frame turns them more than 15° (or 720°/s over a long frame)", jumps and not bad, f"max {worst[0]:.1f}° in {worst[1] * 1000:.0f} ms; {len(bad)} over; {hitches} frames over 50 ms left out")
    for off, walk, look in steady:
        seg = max((g for g in segs if g and abs(abs(off_of(g[0])) - off) < 6), key=len, default=None)
        if not seg or seg[-1]["t"] - seg[0]["t"] < 3.5:
            c.check(s, f"steady {off}°: a segment of at least 3.5 s", False, f"{len(seg or [])} frames")
            continue
        t0 = seg[0]["t"] + 2.0
        st = [r for r in seg if r["t"] >= t0]
        # The drawn speed: the median of 0.5 s windows' net displacement (the drawn track's
        # per-frame steps jitter at segment renewals, and a window over a snap is an outlier).
        # Frames up to 2.5 s after a jump of the display clock (a resync) are left out: the drawn
        # body leaps, then closes the gap at up to `live.rs` CATCH_UP faster than the authority.
        jumps_at = [b["t"] for a, b in zip(rows, rows[1:]) if a.get("mine_ms") is not None and b.get("mine_ms") is not None and (b["mine_ms"] - a["mine_ms"]) - (b["t"] - a["t"]) * 1000 > 300]
        recovering = lambda t: any(0 <= t - x < 2.5 for x in jumps_at)
        wins, j = [], 0
        for i, r in enumerate(st):
            while st[j]["t"] < r["t"] - 0.5:
                j += 1
            # A window over a jump of the display clock (a resync: the drawn body leaps, then
            # catches up) says nothing about the gait; the authority's speed is the ground speed.
            jumped = r.get("mine_ms") is not None and st[j].get("mine_ms") is not None and (r["mine_ms"] - st[j]["mine_ms"]) - (r["t"] - st[j]["t"]) * 1000 > 300
            if r["t"] - st[j]["t"] >= 0.45 and not jumped and not recovering(r["t"]) and not recovering(st[j]["t"]):
                d = ((r["sim"][0] - st[j]["sim"][0]) ** 2 + (r["sim"][1] - st[j]["sim"][1]) ** 2) ** 0.5 / (r["t"] - st[j]["t"])
                a = statistics.median(x["seg"][2] for x in st[j:i + 1] if x.get("seg")) if any(x.get("seg") for x in st[j:i + 1]) else 0.0
                wins.append((d, d / a if a > 0.3 else None))
        v = statistics.median(w[0] for w in wins) if wins else 0.0
        # The drawn speed against the authority's over the same windows, where the segment speed
        # is the stretch's own (±2%): onto a road the newest segment's speed (`mine_seg`) trails
        # the road share and the drawn track runs ~10% ahead of it, which is not the gait's.
        auth = statistics.median(r["seg"][2] for r in st if r.get("seg"))
        ratios = [w[1] for w in wins if w[1] is not None and abs(w[0] / w[1] / auth - 1) <= 0.02]
        ratio = statistics.median(ratios) if ratios else 0.0
        # The authority's segment speed is the ground speed the rules give the body.
        auth = statistics.median(r["seg"][2] for r in st if r.get("seg"))
        crossed = [r for r in st if r["crossed"]]
        legs = statistics.median(abs(r["legs_off"]) for r in st if r["legs_off"] is not None)
        # Forward: turned toward the look by what the head and chest leave, at most `body`;
        # backwards (past the back limit): the same from the travel's reverse.
        want = 180.0 - min(max((180 - off) - upper, 0), body) if off > LOOK_WALK_BACK.get(preset, 135) else min(max(off - upper, 0), body)
        row = {"off": off, "speed": round(v, 3), "drawn_over_authority": round(ratio, 3), "drawn_windows": len(ratios), "clock_jumps": len([x for x in jumps_at if st[0]["t"] - 2.5 <= x <= st[-1]["t"]]), "authority_speed": auth, "legs_off_median": round(legs, 1), "legs_want": want, "crossed_frames": len(crossed), "frames": len(st),
               "min_sep_m": round(min((r["sep"] for r in st if r["sep"] is not None), default=0), 3), "own_overlap_frames": sum(1 for r in st if r["own_overlap"]), "cross_weight_max": round(max(r["cross_w"] for r in st), 2)}
        row["crossed_at"] = [{"t": round(r["t"] - seg[0]["t"], 2), "legs_off": round(r["legs_off"], 1), "sep": round(r["sep"], 3) if r["sep"] is not None else None, "cross_w": round(r["cross_w"], 2), "gaits": [(n, round(w, 2)) for n, w in (r.get("gaits") or []) if w > 0.05], "look_off": round(wrapd(r["look"] - r["heading"]), 1)} for r in crossed[:12]]
        result["segments"].append(row)
        if off == 0:
            base_v, base_auth = v, auth
        if off <= upper:
            c.check(s, f"steady {off}° (within head+chest {upper}°): no crossing", not crossed, f"{len(crossed)}/{len(st)} frames, min sep {row['min_sep_m']} m, cross weight {row['cross_weight_max']}")
        else:
            c.check(s, f"steady {off}° (past head+chest): no crossing once the body has come round", not crossed, f"{len(crossed)}/{len(st)} frames")
        c.check(s, f"steady {off}°: the legs settle {want:.0f}° off the travel (±8°)", abs(legs - want) <= 8, f"{legs:.1f}°")
        # Along the keys: the authority's travel heading against the keys' way (compass `walk`,
        # sim = compass − 90°), times its speed against straight walking's. look-2: a look turns
        # only the facing, so this is 1.00× at every look (before it, 0.87× past a 30° look).
        keys = walk - 90.0
        hd = statistics.median(wrapd(r["heading"] - keys) for r in st)
        row["travel_off_keys_deg"] = round(hd, 2)
        if base_v:
            along = auth * math.cos(math.radians(hd)) / base_auth
            row["along_keys"] = round(along, 4)
            c.check(s, f"steady {off}°: ground speed along the keys 1.00× (±1%)", abs(along - 1) <= 0.01 and abs(hd) < 2.0, f"{along:.4f}×, travel {hd:+.2f}° off the keys")
        if base_v and off:
            c.check(s, f"steady {off}°: the authority's ground speed as straight (±2%)", abs(auth / base_auth - 1) <= 0.02, f"{auth:.3f} vs {base_auth:.3f} m/s")
        # A segment the display clock jumped in (a resync, `bodies.rs`) is left out here and said
        # so in look_walk.json: the drawn track recovers at its own pace, which is the client's
        # clock and not the gait (the authority's speed above is the ground speed).
        if row["clock_jumps"]:
            row["drawn_check"] = f"skipped: {row['clock_jumps']} display-clock jump(s)"
        else:
            c.check(s, f"steady {off}°: the drawn speed is the authority's (±8%, over the same windows)", abs(ratio - 1) <= 0.08 and len(ratios) >= 3, f"{ratio:.3f} of it ({v:.2f} m/s drawn) over {len(ratios)} windows")
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
        # Until the travel changes again (a resident in the way, the stop).
        new_h = None
        after = []
        for r in rows[i0:]:
            if r["t"] - t_s >= 3.5 or r.get("heading") is None:
                break
            if r["t"] - t_s > 0.8:
                new_h = r["heading"] if new_h is None else new_h
                if abs(wrapd(r["heading"] - new_h)) > 20:
                    break
            if r["v"] > 0.5:
                after.append(r)
        crossed = [r for r in after if r["crossed"]]
        last = (crossed[-1]["t"] - t_s) if crossed else 0.0
        result[f"sudden{turn}"] = {"crossed_frames": len(crossed), "last_cross_s": round(last, 2), "limit_s": round(limit, 2), "cross_weight_max": round(max([r["cross_w"] for r in after] or [0]), 2), "own_overlap_frames": sum(1 for r in after if r["own_overlap"])}
        c.check(s, f"sudden {turn}°: any crossing ends within {limit:.2f} s", last <= limit, f"last crossing {last:.2f} s after the turn ({len(crossed)} frames)")
    json.dump(result, open(os.path.join(out, "look_walk.json"), "w"), indent=1)
    return result


LOOK_WALK_BACK = {"head": 130, "chest": 135, "loose": 155}
LOOK_WALK_SPOT = (300.0, 330.0)


def look_walk_others(run, c):
    """Another player's body as I draw it (look-3): verify.py's player identity walks east beside
    me with its look held north (`human_move`, then `human_face`, as that player). The authority
    keeps its travel east at full speed and turns its facing 75° north (`look_walk_deg`); my
    client draws that body's legs on its travel and its upper body twisted toward the facing
    (the look target from the row, `live.rs` `authority_facing`), logged as `LIVING_GAME_FEET_ID`."""
    s = "look-walk:others"
    if "token" not in json.load(open(os.path.join(ROOT, ".local/living/verify", run, "state.json"))):
        subprocess.run([sys.executable, V, "player", "--run", run, "join", "Bender"], capture_output=True, text=True)
    r = subprocess.run([sys.executable, V, "sql", "--run", run, "SELECT id FROM my_body", "--as-player"], capture_output=True, text=True)
    t = r.stdout
    other = json.loads(t[t.find("["):])[0]["id"] if "[" in t else None
    c.check(s, "a second player to walk beside me", other is not None, t[-200:])
    if other is None:
        return
    snap = f"sql|SELECT id, x, y, heading, turn, turn_s, t_ms, next_ms, vx, vy, speed, face_off, face_turn, face_turn_s FROM body WHERE id = {other}"
    plan = ("ready;click:@tip:ok;sync:spot;wait:5;frame:0;view:30:9;lookwalk:chest;wait:1;sync:other;wait:2;sync:go;wait:3;sync:walking;shot:01_other_walking;wait:2;"
            "sync:halt;wait:2.5;quit")
    syncs = [f"spot=place_at|{{me}}|{LOOK_WALK_SPOT[0]}|{LOOK_WALK_SPOT[1]}", f"other=place_at|{other}|(mx-4)|(my+3)",
             f"go=player|human_move|1|0|false;player|human_face|0|-1", f"walking={snap}", "halt=player|human_move|0|0|false;player|human_face|0|0"]
    name = "look-walk-others"
    out_dir = os.path.join(ROOT, ".local/living/verify", run, "ui", name)
    os.makedirs(out_dir, exist_ok=True)
    keep = {k: os.environ.get(k) for k in ["LIVING_GAME_FEET", "LIVING_GAME_FEET_ID", "LIVING_GAME_CONTROL"]}
    os.environ.update({"LIVING_GAME_FEET": os.path.join(out_dir, "feet.jsonl"), "LIVING_GAME_FEET_ID": str(other), "LIVING_GAME_CONTROL": "cursor"})
    try:
        out, code, text = drive(run, name, plan, syncs=syncs)
    finally:
        for k, v in keep.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    c.check(s, "client ran and joined", code == 0, text[-300:])
    scene = json.load(open(os.path.join(out, "scene.json"))) if os.path.exists(os.path.join(out, "scene.json")) else {}
    b = ((scene.get("snaps") or {}).get("walking") or [{}])[0]
    row = (b.get("rows") or [None])[0]
    if row:
        speed = math.hypot(row["vx"], row["vy"])
        f = math.degrees(facing_at(row, b["wall_ms"]))
        h = math.degrees(heading_at(row, b["wall_ms"]))
        c.check(s, "the authority: their travel east at full speed (1.00× along the keys)", abs(wrapd(h)) < 2.0 and abs(row["vx"] / row["speed"] - 1) <= 0.01, f"travel {h:+.1f}°, vx {row['vx']:.3f} of speed {row['speed']:.3f}, |v| {speed:.3f}")
        c.check(s, "the authority: their facing 75° north of the travel (look_walk_deg)", abs(wrapd(f - h) + 75.0) < 4.0, f"facing {f:+.1f}°, {wrapd(f - h):+.1f}° off the travel")
    else:
        c.check(s, "the authority's row while they walk", False, json.dumps(b)[-200:])
    lines = [x for x in feet_log(out) if x.get("id") == other and x.get("heading") is not None]
    t_go = None
    for x in lines:
        if abs(wrapd(x["heading"])) < 3 and (x.get("twist") or 0) < -40:
            t_go = x["t"] if t_go is None else t_go
    walking = [x for x in lines if t_go is not None and x["t"] >= t_go + 1.0 and abs(wrapd(x["heading"])) < 3]
    walking = walking[: max(1, len(walking) * 2 // 3)]
    c.check(s, "my client logged their body walking with its look held", len(walking) > 30, f"{len(walking)} frames")
    if len(walking) > 30:
        import statistics
        tw = statistics.median(x["twist"] for x in walking)
        legs = statistics.median(abs(wrapd(x["yaw"] - 180.0 - x["heading"])) for x in walking)
        c.check(s, "drawn: their upper body twists toward the authority's facing (−75° ± 6)", abs(tw + 75.0) <= 6.0, f"twist {tw:+.1f}°")
        c.check(s, "drawn: their legs stay on their travel (±8°)", legs <= 8.0, f"legs {legs:.1f}° off")
        json.dump({"other": other, "twist_median": tw, "legs_off_median": legs, "frames": len(walking), "authority": row}, open(os.path.join(out, "others.json"), "w"), indent=1)


def look_walk(run, c):
    """`look-walk` (play-test 5, item 2): every preset, or `LOOK_WALK_PRESETS=chest,head`;
    `LOOK_WALK_REUSE=1` checks the last drives' feet logs again, `LOOK_WALK_RECORD=1` also records
    the session (`LIVING_GAME_RECORD`, stills for a video), `LOOK_WALK_TOKEN=FILE` walks another
    character (a tired one walks at 0.6 of the pace, where the old client crossed its legs)."""
    for p in [x for x in os.environ.get("LOOK_WALK_PRESETS", "head,chest,loose").split(",") if x]:
        look_walk_one(run, c, p)
    if os.environ.get("LOOK_WALK_REUSE"):
        return
    look_walk_others(run, c)
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


def wheel(run, c):
    """The wheel (docs/INTERFACE.md §8): hold F on a resident, the held cursor picks a section,
    letting go chooses; Esc and the hub send nothing; a flick opens it with its direction; a
    digit chooses at once; the cursor is where it was after each (1 px)."""
    s = "wheel"
    a, b = residents(run)
    P = "point:{A}:1.0;wait:0.6"
    plan = ("ready;sync:scene;wait:2;" + P + ";dump:00;"
            # Held: open, toward nw (wave), let go.
            "key:KeyF:down;wait:0.5;shot:01_open;dump:01;nudge:-42,-42;wait:0.3;shot:02_wave;dump:02;key:KeyF:up;wait:1.5;dump:03;"
            # Esc closes it: nothing sent.
            + P + ";key:KeyF:down;wait:0.5;nudge:60,0;wait:0.2;key:Escape:tap;wait:0.3;dump:04;key:KeyF:up;wait:0.5;dump:05;"
            # Let go in the hub: nothing sent.
            + P + ";key:KeyF:down;wait:0.5;key:KeyF:up;wait:0.5;dump:06;"
            # A flick: F and a quick move east before it would draw: it opens with east chosen.
            + P + ";key:KeyF:down;wait:0.12;nudge:45,0;wait:0.1;dump:07;key:KeyF:up;wait:0.8;dump:08;key:Escape:tap;wait:0.3;key:Escape:tap;wait:0.3;"
            # A digit chooses at once (1 is north: Talk).
            + P + ";key:KeyF:down;wait:0.5;key:Digit1:tap;wait:0.6;dump:09;key:KeyF:up;wait:0.3;key:Escape:tap;wait:0.3;dump:10;quit").replace("{A}", str(a))
    out, code, text = drive(run, s, plan, places=[f"{a}:-1.8:1.2", f"{b}:2.0:-2.0"])
    c.check(s, "client ran and joined", code == 0, text[-300:])
    d = {k: dump(out, k) for k in ["00", "01", "02", "03", "04", "05", "06", "07", "08", "09", "10"]}
    w = lambda k: (d[k] or {}).get("wheel") or {}
    cur = lambda k: (((d[k] or {}).get("extra") or {}).get("cursor") or {})
    L = log(out)
    secs = {x["dir"]: x["what"] for x in w("01").get("sections", [])}
    c.check(s, "holding F on a person opens its wheel, held, with the pinned layout", w("01").get("held") is True and secs == {"n": "talk", "ne": "give", "e": "offer", "se": "teach", "s": "more", "sw": "window", "w": "appraise", "nw": "wave"}, str(secs))
    c.check(s, "the drawn cursor is held: it has not moved while the wheel is open", cur("01").get("x") == cur("00").get("x") and cur("02").get("x") == cur("00").get("x"), str((cur("00"), cur("02"))))
    c.check(s, "moving toward nw selects Wave (the hub names it)", w("02").get("sel") == "nw", str(w("02").get("sel")))
    seg = L.split("ui: wheel chose nw wave", 1)
    c.check(s, "letting go sends the rules' wave toward them (human_act)", len(seg) == 2 and re.search(rf'verbs: .* → \{{"do":"wave","target":\{{"id":{a}\}}\}}', seg[1]) is not None, seg[1][:300] if len(seg) == 2 else "not chosen")
    c.check(s, "and its outcome is noted in the rules' words", len((d["03"] or {}).get("notes") or []) > 0, str((d["03"] or {}).get("notes")))
    def quiet(after, until):
        t = L.split(after, 1)
        return len(t) == 2 and re.search(r'→ \{"do"', t[1].split(until, 1)[0]) is None
    c.check(s, "Esc closes it and nothing is sent", not w("04") and "ui: wheel closed (Esc): nothing sent" in L and quiet("ui: wheel closed (Esc)", "ui: wheel toward"), "")
    c.check(s, "letting go in the hub sends nothing", "ui: wheel chose the hub: nothing sent" in L and not w("06") and quiet("ui: wheel chose the hub", "ui: wheel toward"), "")
    c.check(s, "a flick opens it with its direction chosen (east: Offer)", w("07").get("sel") == "e" and "ui: wheel chose e offer" in L, str(w("07")))
    c.check(s, "and Offer's further choice opens its sub-list", ((d["08"] or {}).get("acts") or {}).get("group") == "offer", str((d["08"] or {}).get("acts")))
    c.check(s, "a digit chooses at once (1, north: Talk opens the box to them)", "ui: wheel chose n talk" in L and ((d["09"] or {}).get("typing") or {}).get("to") == a, str((d["09"] or {}).get("typing")))
    for k in ["03", "05", "06", "10"]:
        x0, x1 = cur("00"), cur(k)
        ok = x0 and x1 and abs(x0["x"] - x1["x"]) <= 1 and abs(x0["y"] - x1["y"]) <= 1
        c.check(s, f"after closing ({k}) the cursor is where it was (1 px)", bool(ok), str((x0, x1)))


def wheel_workplace(run, c):
    """A fuel fire's wheel on Cullet (a furnace, oven, hearth or smokehouse with no one by it):
    Make pinned north and Feed east; with the fire out, Make
    greys with the rules' reason in the hub, and choosing it still sends it (the authority
    decides; its words are noted)."""
    s = "wheel-workplace"
    # A fuel fire with no one standing by it: a creature under the cursor is aimed before a thing.
    fs = sql(run, "SELECT id, kind, x, y, lit_until_ms FROM structure WHERE kind = 'furnace' OR kind = 'oven' OR kind = 'hearth' OR kind = 'smokehouse'")
    bodies = sql(run, "SELECT id, x, y FROM body")
    alone = lambda f: min([((b["x"] - f["x"]) ** 2 + (b["y"] - f["y"]) ** 2) ** 0.5 for b in bodies] or [99.0])
    fs.sort(key=alone, reverse=True)
    c.check(s, "the world has a fuel fire with no one by it", len(fs) > 0 and alone(fs[0]) > 6.0, str([(f["kind"], f["id"], round(alone(f), 1)) for f in fs[:3]]))
    if not fs:
        return
    f = fs[0]
    plan = (f"ready;wait:2;sync:there;wait:6;pointat:{f['x']},{f['y']}:0.8;wait:0.8;dump:00;key:KeyF:down;wait:0.5;shot:01_open;dump:01;"
            "nudge:0,-50;wait:0.3;shot:02_make;dump:02;key:KeyF:up;wait:1;shot:03_grid;dump:03;key:Digit1:tap;wait:2;shot:04_sent;dump:04;quit")
    # Beside the furnace (admin place_at, scene setup); F aims at the nearest thing.
    there = f"there=place_at|{{me}}|{f['x'] + 1.2}|{f['y']}"
    out, code, text = drive(run, s, plan, syncs=[there])
    c.check(s, "client ran and joined", code == 0, text[-300:])
    d = {k: dump(out, k) for k in ["00", "01", "02", "03", "04"]}
    w = lambda k: (d[k] or {}).get("wheel") or {}
    secs = {x["dir"]: x for x in w("01").get("sections", [])}
    c.check(s, f"F held at a {f['kind']} opens its wheel: Make north, Feed east", secs.get("n", {}).get("what") == "make" and secs.get("e", {}).get("what") == "feed", str({k: v["what"] for k, v in secs.items()}))
    mk = secs.get("n", {})
    c.check(s, "with the fire out, Make greys with the rules' reason", mk.get("allowed") is False and bool(mk.get("reason")), str(mk))
    L = log(out)
    # Make is a way of making with a recipe grid: choosing it opens the grid (its cells greyed with
    # the rules' reasons), and a greyed cell is still sent (grey is a hint).
    g3 = (d["03"] or {}).get("grid") or {}
    c.check(s, "choosing it opens Make's recipe grid, its cells greyed with the rules' reasons", g3.get("skill") == "make" and g3.get("cells") and all(x["reason"] for x in g3["cells"] if not x["allowed"]), str([(x["product"], x["allowed"]) for x in g3.get("cells") or []][:4]))
    c.check(s, "a greyed cell is still sent (grey is a hint)", re.search(r"ui: grid make chose \w+ \(grey", L) is not None and re.search(r'verbs: .* → \{"do":"make"', L) is not None)
    c.check(s, "and the authority's words are noted", len((d["04"] or {}).get("notes") or []) > 0, str((d["04"] or {}).get("notes")))


def grid(run, c):
    """A recipe grid (recipes-1, docs/INTERFACE.md example 4), on Cullet: at a cold hearth the
    wheel's Make opens the grid, every cell greyed with the rules' reason; fed (Feed › wood) it
    burns, and with 4 kelp Ash is live; choosing its cell makes ash (the authority's own act)."""
    s = "grid"
    fs = sql(run, "SELECT id, kind, x, y FROM structure WHERE kind = 'hearth'")
    bodies = sql(run, "SELECT id, x, y FROM body")
    alone = lambda f: min([((b["x"] - f["x"]) ** 2 + (b["y"] - f["y"]) ** 2) ** 0.5 for b in bodies] or [99.0])
    fs.sort(key=alone, reverse=True)
    c.check(s, "the world has a hearth with no one by it", len(fs) > 0 and alone(fs[0]) > 6.0, str([(f["id"], round(alone(f), 1)) for f in fs[:3]]))
    if not fs:
        return
    f = fs[0]
    P = f"pointat:{f['x']},{f['y']}:0.8;wait:0.8"
    make = P + ";key:KeyF:down;wait:0.5;nudge:0,-50;wait:0.3;key:KeyF:up;wait:1"
    plan = (f"ready;wait:2;sync:there;wait:6;" + make + ";shot:01_cold;dump:01;key:Escape:tap;wait:0.3;"
            "sync:kit;wait:1;" + P + ";key:KeyF:down;wait:0.5;nudge:50,0;wait:0.3;key:KeyF:up;wait:1;dump:02;click:@acts:1:wood;wait:4;dump:03;"
            + make + ";shot:02_lit;dump:04;key:Digit1:tap;wait:2;dump:05;wait:12;dump:06;quit")
    there = f"there=place_at|{{me}}|{f['x'] + 1.2}|{f['y']}"
    kit = 'kit=grant_items|{me}|"kelp"|4;grant_items|{me}|"wood"|3'
    me0 = None
    out, code, text = drive(run, s, plan, syncs=[there, kit])
    c.check(s, "client ran and joined", code == 0, text[-300:])
    d = {k: dump(out, k) for k in ["01", "02", "03", "04", "05"]}
    g = lambda k: (d[k] or {}).get("grid") or {}
    cells = lambda k: g(k).get("cells") or []
    c.check(s, "at a cold hearth, Make opens its recipe grid: a cell per product", len(cells("01")) > 1 and g("01").get("skill") == "make", str([x["product"] for x in cells("01")]))
    c.check(s, "a cell is greyed exactly when the rules refuse it, with their own reason", cells("01") and all(x["allowed"] == (not x["reason"]) for x in cells("01")) and any(not x["allowed"] for x in cells("01")), str([(x["product"], x["reason"][:40]) for x in cells("01")]))
    ash = [x for x in cells("01") if x["product"] == "ash"]
    c.check(s, "a cell's rows are its recipe (takes, where, time) and its detail made_how", bool(ash) and any(r[0] == "Takes" and "kelp" in r[1] for r in ash[0]["rows"]) and any(r[0] == "Where" for r in ash[0]["rows"]) and "kelp" in ash[0]["detail"], str(ash[:1]))
    L = log(out)
    # A household's hearth is usually burning already: Feed is then refused as full, in the
    # rules' words (feed's "fuel" puts on the first fuel I carry).
    c.check(s, "Feed is sent from the wheel and the authority answers it", re.search(r'verbs: .* → \{"do":"feed"', L) is not None, "")
    lit = [x for x in cells("04") if x["product"] == "ash"]
    c.check(s, "burning, with 4 kelp, Ash is live", bool(lit) and lit[0]["allowed"], str(lit[:1]))
    first = (cells("04") or [{}])[0].get("product")
    c.check(s, "choosing its cell (1) sends make with its item", re.search(rf'verbs: .* → \{{"do":"make","item":"{first}"', L) is not None, first or "")
    me = json.load(open(os.path.join(out, "scene.json"))).get("me")
    got = sum(r["qty"] for r in sql(run, f"SELECT item, qty FROM inventory WHERE owner = {me} AND item = 'ash'")) if me else 0
    c.check(s, "the authority made it: ash in the pack", first != "ash" or got >= 1, f"ash {got}")


def walk_law(run, c):
    """Settings › Play › Walk speed (stamina-1 made walk_base live): the row reads the world's
    `walk_base` law from the installed script and, through a play scene's admin link, writes it
    (`set_world_law`), as the authority records (`law_change`)."""
    s = "walk-law"
    plan = ("ready;wait:3;click:@menu;wait:0.4;click:@menu:Settings;wait:0.8;dump:01;shot:01_walk;"
            "click:@settings:walk:3.0;wait:4;dump:02;shot:02_walk_3;click:@settings:walk:2.6;wait:4;dump:03;quit")
    out, code, text = drive(run, s, plan, extra=["--admin-link"])
    c.check(s, "client ran and joined", code == 0, text[-300:])
    fs = lambda k: (((dump(out, k) or {}).get("extra") or {}).get("facing_sight") or {})
    c.check(s, "the row reads walk_base from the installed script (2.6 m/s)", abs((fs("01").get("walk") or 0) - 2.6) < 0.05 and "settings:walk:3.0" in ((dump(out, "01") or {}).get("tags") or {}), str(fs("01")))
    c.check(s, "with the admin link it can change it", fs("01").get("can_switch") is True, str(fs("01")))
    changes = [r for r in sql(run, "SELECT name, old, new FROM law_change WHERE name = 'walk_base'")]
    c.check(s, "3.0 is written as the world's law and read back", abs((fs("02").get("walk") or 0) - 3.0) < 0.05 and any(r.get("new") == "3.0" for r in changes), f"{fs('02').get('walk')}; {changes}")
    c.check(s, "and 2.6 again", abs((fs("03").get("walk") or 0) - 2.6) < 0.05 and any(r.get("new") == "2.6" for r in changes), f"{fs('03').get('walk')}; {changes}")


def pools(run, c):
    """stamina-1's pools on the bar: the focus bar ("Mana", `while_short`) shows only while short;
    a slot whose pool is short of its cost greys in the rules' own words (`short_of`: "not enough
    mana"). The scene lowers `focus_max` to 40 (admin `set_world_law`) so one fire bolt leaves too
    little for a heal (35) or another bolt (30), and restores it after."""
    s = "pools"
    # A fire bolt (R, 30 mana; drawn first: a hostile move) at a point on the ground: 10 of 40 left.
    plan = ("ready;wait:2;sync:low;wait:3;dump:00;key:KeyX:tap;wait:0.5;cursor:0.5,0.3;wait:0.3;key:KeyR:down;wait:0.4;key:KeyR:up;wait:2;shot:01_short;dump:01;wait:3;dump:01b;"
            "key:KeyX:tap;sync:back;wait:14;dump:02;quit")
    low = 'low=set_world_law|"focus_max"|"40"'
    back = 'back=set_world_law|"focus_max"|"100"'
    out, code, text = drive(run, s, plan, syncs=[low, back])
    c.check(s, "client ran and joined", code == 0, text[-300:])
    d = {k: dump(out, k) for k in ["00", "01", "01b", "02"]}
    ms = lambda k: {m["name"]: m for m in (((d[k] or {}).get("me") or {}).get("meters") or [])}
    slot = lambda k, n: (((d[k] or {}).get("extra") or {}).get("slots") or {}).get(f"bar:{n}") or {}
    c.check(s, "full, the mana bar is not shown (while_short)", "focus" not in ms("00"), str(list(ms("00"))))
    f = ms("01").get("focus")
    c.check(s, "after a fire bolt it shows, short", f is not None and f["value"] < f["max"], str(f))
    # The bolt's own slot cools down first (a cooldown shows before a pool), then greys too.
    heal, bolt = slot("01", "Skill2"), slot("01b", "Skill3")
    fb = ms("01b").get("focus") or {}
    c.check(s, "a slot whose pool is short of its cost greys in the rules' words (heal; the bolt once cooled down: not enough mana)", "mana" in (heal.get("off") or "").lower() and "mana" in (bolt.get("off") or "").lower() and fb.get("value", 99) < 30, str((heal.get("off"), bolt.get("off"), fb.get("value"))))
    c.check(s, "a slot of another pool is not greyed by it (strike: stamina)", "mana" not in (slot("01", "Primary").get("off") or "").lower(), str(slot("01", "Primary").get("off")))
    c.check(s, "refilled to its max again, the mana bar goes", "focus" not in ms("02"), str(list(ms("02"))))


def own(run, c):
    """mind-act-outcome-far (force_outcomes): my own strikes, shots and casts get an `own`
    act_outcome row and experience line. The client takes notes and Log events only from `act`
    and `record` rows, so the `own` rows add no note or Log line: no second word on a strike the
    bar already answers, no line per blow. Drawn, three strikes at no one, a bow shot and a fire
    bolt at the ground, then the Log."""
    s = "own"
    plan = ("ready;wait:2;key:KeyX:tap;wait:0.6;cursor:0.5,0.3;wait:0.3;tap;wait:0.7;tap;wait:0.7;tap;wait:0.7;"
            "mouse:right:down;wait:0.5;mouse:right:up;wait:2;key:KeyR:down;wait:0.4;key:KeyR:up;wait:3;dump:01;"
            "key:KeyL:tap;wait:0.6;shot:02_log;dump:02;key:KeyX:tap;wait:0.4;quit")
    out, code, text = drive(run, s, plan)
    c.check(s, "client ran and joined", code == 0, text[-300:])
    sc = json.load(open(os.path.join(out, "scene.json"))) if os.path.exists(os.path.join(out, "scene.json")) else {}
    me = sc.get("me")
    rows = sql(run, f"SELECT id, kind, ok, skill, what, why FROM act_outcome WHERE observer = {me} AND kind = 'own'") if me else []
    texts = [r.get("text", "") for r in (sql(run, f"SELECT id, text FROM experience WHERE observer = {me} AND kind = 'own'") if me else [])]
    c.check(s, "the authority told me how my shot and bolt came out (own rows)", len(rows) >= 2 and {"bowshot", "firebolt"} <= {r.get("skill") for r in rows}, str(rows)[:600])
    d = {k: dump(out, k) or {} for k in ["01", "02"]}
    shown = [n for k in d for n in (d[k].get("notes") or [])] + [e for k in d for e in ((d[k].get("extra") or {}).get("events") or [])]
    words = [w for r in rows for w in [r.get("why", "")] if w] + [t for t in texts if t]
    hit = [x for x in shown if any(w and (w in x or x in w) for w in words) or x.startswith("You finished") or x.startswith("You failed to")]
    c.check(s, "no note or Log event repeats an own row", not hit, str(hit)[:400])
    notes = d["01"].get("notes") or []
    c.check(s, "no line per blow: at most one note per strike, none for the shot or bolt", len(notes) <= 3 and all(notes.count(n) <= 3 for n in notes), str(notes))
    c.check(s, "the Log is open", "Log" in [w for w, _ in wins(d["02"])], str(wins(d["02"])))


UNHEARD_SPOT = (300.0, 330.0)


def unheard(run, c):
    """speech-truth (`speech_truth`, on by default): a line nobody could hear gets the authority's
    truthful `silence` row and a `reach` act outcome. The client shows those words once, as a
    quiet note; the Log does not repeat them (only my line's "did not hear you" mark), and a room
    line nobody heard gets no client-made "No one in earshot" note beside them. A heard line gets
    none. Speech carries 9 m and a person sees 11 m by day (6 m by night): the scene stands me on
    open grass at noon (a scratch fixture) with one resident held 10 m away, seen but out of
    earshot ("… is too far away: they could not have heard you."), then beside me."""
    s = "unheard"
    b = residents(run, 1)[0]
    # Earlier scenes leave residents held where the player stood: anyone within 25 m of the spot
    # (but me and B) is put 40 m east first, and stays (held, or walks back slowly).
    people = {r["id"]: r.get("name") for r in sql(run, "SELECT id, name, kind FROM character WHERE kind = 'person'")}
    near0 = [r for r in sql(run, "SELECT id, x, y FROM body") if r["id"] in people and r["id"] != b and people[r["id"]] != "Verifier"
             and ((r["x"] - UNHEARD_SPOT[0]) ** 2 + (r["y"] - UNHEARD_SPOT[1]) ** 2) ** 0.5 < 25]
    clear = ";".join(f"place_at|{r['id']}|{UNHEARD_SPOT[0] + 40}|{UNHEARD_SPOT[1] + 3 * i}" for i, r in enumerate(near0)) or "sql|SELECT id FROM world"
    plan = ("ready;sync:noon;sync:clear;sync:spot;wait:2;sync:scene;wait:0.5;sync:bodies;wait:2;dump:00;"
            "point:{B};wait:0.5;key:Enter:tap;wait:0.6;dump:01;type:Can you hear me over there?;enter;wait:2.5;shot:01_far;dump:02;"
            "cursor:0.5,0.12;wait:0.4;key:Enter:tap;wait:0.6;dump:03a;type:Is anyone here?;enter;wait:2.5;shot:02_room;dump:03;wait:10;dump:04;"
            "wait:0.3;shot:03_log;dump:05;"
            "sync:near;wait:2;point:{B};wait:0.5;key:Enter:tap;wait:0.6;type:Hello, now you are close.;enter;wait:3;shot:04_heard;dump:06;key:Escape:tap;wait:0.3;quit").replace("{B}", str(b))
    syncs = ["noon=sql|UPDATE world SET epoch_ms = {epoch_at:12} WHERE id = 0", f"clear={clear}", f"spot=place_at|{{me}}|{UNHEARD_SPOT[0]}|{UNHEARD_SPOT[1]}", "bodies=sql|SELECT id, x, y FROM body", f"near=place_at|{b}|(mx+1.6)|(my+1.2)"]
    out, code, text = drive(run, s, plan, places=[f"{b}:0:10"], syncs=syncs)
    c.check(s, "client ran and joined", code == 0, text[-300:])
    sc = json.load(open(os.path.join(out, "scene.json"))) if os.path.exists(os.path.join(out, "scene.json")) else {}
    me = sc.get("me")
    d = {k: dump(out, k) or {} for k in ["00", "01", "02", "03a", "03", "04", "05", "06"]}
    # The premise: nobody but the held resident within 18 m of me as the scene began.
    snap0 = ((sc.get("snaps") or {}).get("bodies") or [{}])[0]
    rows_b = snap0.get("rows") or []
    since = snap0.get("wall_ms", 0) - 2000
    at = {r["id"]: (r["x"], r["y"]) for r in rows_b if "x" in r}
    mine = at.get(me)
    dist = lambda p: ((p[0] - mine[0]) ** 2 + (p[1] - mine[1]) ** 2) ** 0.5
    near = sorted(i for i, p in at.items() if i in people and i != me and dist(p) < 9.5) if mine else None
    bd = round(dist(at[b]), 1) if mine and b in at else None
    c.check(s, "scene: no one within 9 m of me (speech carries 9 m); the resident held 10 m away, within sight (11 m)", near == [] and bd is not None and 9.2 < bd < 10.8, f"me {mine}; within 9.5 m {near}; #{b} at {bd} m")
    t1 = d["01"].get("typing") or {}
    c.check(s, "addressing them far away: the box says out of earshot", t1.get("to") == b and "out of earshot" in (t1.get("label") or ""), json.dumps(t1))
    reach = [r for r in (sql(run, f"SELECT id, kind, ok, code, what, why, other, at_ms FROM act_outcome WHERE observer = {me} AND code = 'reach'") if me else []) if r.get("at_ms", 0) >= since]
    reach.sort(key=lambda r: r.get("at_ms", 0))
    far = [r for r in reach if r.get("other") == b]
    room = [r for r in reach if r.get("other") == 0]
    c.check(s, "the authority: a reach row for the line to them and one for the room line", len(far) == 1 and len(room) == 1 and room[0].get("why") == "Nobody was near enough to hear you." and "could not have heard you" in far[0].get("why", ""), str(reach)[:600])
    def shown(k, words):
        return sum(1 for n in d[k].get("notes") or [] if words and words in n)
    fw = far[0]["why"] if far else None
    rw = room[0]["why"] if room else None
    c.check(s, "the words for the line to them show once, as a note", fw is not None and shown("02", fw) == 1 and all(shown(k, fw) <= 1 for k in d), f"{fw!r} in notes {d['02'].get('notes')}")
    c.check(s, "the words for the room line show once, as a note", rw is not None and shown("03", rw) == 1 and all(shown(k, rw) <= 1 for k in d), f"{rw!r} in notes {d['03'].get('notes')}")
    L = log(out)
    c.check(s, "no client-made room note beside them (No one in earshot heard you)", "talk: room note" not in L and not any("No one in earshot heard you" in n for k in d for n in d[k].get("notes") or []), str(d["04"].get("notes")))
    ev = [e for k in ("05", "06") for e in ((d[k].get("extra") or {}).get("events") or [])]
    c.check(s, "the Log does not repeat them", not any((fw and fw in e) or (rw and rw in e) or "could not have heard" in e or "near enough to hear" in e for e in ev), str(ev)[:400])
    said = [r for r in (sql(run, f"SELECT id, kind, object, text, at_ms FROM experience WHERE observer = {me} AND kind = 'said' AND object = {b}") if me else []) if r.get("at_ms", 0) >= since]
    c.check(s, "a heard line: said to them beside me, and no further reach row", len(said) == 2 and len(reach) == 2, f"said to #{b} in this drive: {len(said)}; reach rows {len(reach)}")
    n6 = d["06"].get("notes") or []
    c.check(s, "a heard line: no reach note", not any("could not have heard" in n or "near enough to hear" in n or "out of earshot" in n for n in n6), str(n6))


SCENARIOS = {"field": field, "windows": windows, "talk": talk, "items": items, "themes": themes, "film": film, "pick": pick, "turns": turns, "look-walk": look_walk, "bar": bar, "offers": offers, "wheel": wheel, "wheel-workplace": wheel_workplace, "grid": grid, "walk-law": walk_law, "pools": pools, "support": support, "own": own, "unheard": unheard}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("scenarios", nargs="*")
    a = ap.parse_args()
    if not f"verify-{a.run}".startswith("verify-ui-"):
        sys.exit("verify-ui runs use run names ui-* (worlds verify-ui-*)")
    c = Checks()
    # `support` needs a Cullet world (`--seed cullet`), the others the island's residents.
    for name in a.scenarios or [k for k in SCENARIOS if k not in ("support", "wheel-workplace", "grid")]:
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
