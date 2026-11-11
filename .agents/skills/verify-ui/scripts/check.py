#!/usr/bin/env python3
"""Run verify-ui scenarios on a verify-ui-* world and check what they did.

  check.py --run RUN [SCENARIO ...]      scenarios: windows talk items themes pick turns bar offers support (default: all but support)
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


def drive(run, name, plan, places=(), syncs=()):
    # A run per theme keeps its own evidence (`LIVING_GAME_THEME=night check.py …`).
    name = f"{name}-{THEME}" if THEME else name
    cmd = [sys.executable, os.path.join(HERE, "drive.py"), "--run", run, "--name", name, "--plan", plan, "--timeout", "420"]
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
            "sync:hold;wait:0.8;dump:04p;point:{A};wait:0.4;shot:04_hover;key:Enter:tap;wait:0.6;shot:05_to_them;dump:05;type:Hello there, good morning.;enter;wait:1.2;shot:06_said;dump:06;"
            "key:Enter:tap;wait:0.4;tab;wait:0.4;dump:07a;tab;wait:0.4;dump:07b;tab;wait:0.4;dump:07c;tab;wait:0.4;dump:07d;tab;wait:0.4;dump:07e;tab;wait:0.4;dump:07f;tab;wait:0.4;dump:07g;tab;wait:0.4;dump:07h;shot:07_tab;key:Escape:tap;wait:0.4;dump:08;"
            "key:KeyL:tap;wait:0.4;click:@log:tab:1;wait:0.4;shot:09_people;click:@log:person:0;wait:0.6;shot:10_window;dump:10;"
            "menu:f@id:{A};wait:0.5;click:@acts:0:window;wait:0.5;click:@person:more;wait:0.5;shot:11_more;click:@acts:0:introduce;wait:0.5;shot:11_intro;dump:11;quit").replace("{A}", str(a))
    # Placed apart across the view, and placed again just before the cursor goes to A: in the
    # 11 s of the room's note they may walk (town life), once onto one spot, stacked on screen.
    wait = json.dumps(json.dumps({"wait": 600}))
    # Open ground on either side of the arrival stall (`place_at` snaps to the nearest walkable
    # tile: spots in the stall put both on one tile, stacked exactly on screen).
    hold = f"hold=place_at|{a}|(mx-3.0)|(my-1.0);set_behavior|{a}|{wait};place_at|{b}|(mx+2.0)|(my-2.0);set_behavior|{b}|{wait}"
    out, code, text = drive(run, s, plan, places=[f"{a}:-3.0:-1.0", f"{b}:2.0:-2.0"], syncs=[hold])
    c.check(s, "client ran and joined", code == 0, text[-300:])
    # The scene first: the two stand apart where they landed, and on screen, before the pick.
    sc = json.load(open(os.path.join(out, "scene.json"))) if os.path.exists(os.path.join(out, "scene.json")) else {}
    at = (sc.get("placed_at") or {}).get("hold") or {}
    pa, pb = at.get(str(a)), at.get(str(b))
    apart_m = ((pa[0] - pb[0]) ** 2 + (pa[1] - pb[1]) ** 2) ** 0.5 if pa and pb else 0
    seen = {x["id"]: x for x in (dump(out, "04p") or {}).get("seen") or []}
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
            "click:@person:offer:{B}:0:0;wait:4;shot:07_agreed;dump:10;quit").replace("{A}", str(a)).replace("{B}", str(b))
    # Goods for the swaps and the terms (admin), then the residents' own acts.
    kit = f'kit=grant_items|{a}|"berries"|4;grant_items|{b}|"berries"|1;grant_items|{{me}}|"wood"|1'
    # Offered again, with the wood for it: the scene leaves nothing standing.
    again = f'grant_items|{{me}}|"wood"|1;{swap}'
    wood0 = inv(a, "wood")
    # Within reach (3 m: the rules refuse an accept from farther, "Out of reach").
    out, code, text = drive(run, s, plan, places=[f"{a}:-1.8:1.2", f"{b}:-0.6:2.2"], syncs=[kit, f"swap={swap}", f"dear={dear}", f"again={again}", f"terms={terms}"])
    c.check(s, "client ran and joined", code == 0, text[-300:])
    d = {k: dump(out, k) for k in ["01", "02", "03", "04", "05", "06", "07", "08", "09", "10"]}
    tags = lambda k: set(((d[k] or {}).get("tags") or {}).keys())
    notes = lambda k: (d[k] or {}).get("notes") or []
    # A card per standing proposal: its acts are the rules' skills on `offer` (Accept, Decline).
    acc, dec = f"person:offer:{a}:0:0", f"person:offer:{a}:0:1"
    c.check(s, "an offer opens their window with Accept and Decline", (f"Person{a}", "Left") in wins(d["01"]) and {acc, dec} <= tags("01"), str((wins(d["01"]), sorted(tags("01")))))
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
    c.check(s, "nothing is left standing toward me", me is not None and sql(run, f"SELECT id FROM trade_offer WHERE to = {me}") == [], str(sql(run, f"SELECT * FROM trade_offer WHERE to = {me}") if me else "?"))
    c.check(s, "and the client reads them as terms (Accept takes them)", re.search(rf"ui: proposal Terms\(\d+\) from #{b}: .*proposes terms: they give 1 berries, you give 1 stone", L) is not None)

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
    st = [dump(out, f"05{k}") or {} for k in "abc"]
    unders = [x.get("under") for x in st]
    def front(x):
        both = [b_ for b_ in (x.get("seen") or []) if b_["id"] in (a, b)]
        return min(both, key=lambda b_: (b_["depth"], b_["id"]))["id"] if len(both) == 2 else None
    c.check(s, "two bodies stacked on one spot: the same one every frame, the nearer the camera", len(set(unders)) == 1 and unders[0] in (a, b) and all(front(x) == unders[0] for x in st), f"under {unders}, front by depth {[front(x) for x in st]}")


def bar(run, c):
    """The cluster on the rules' bar (`bar_places`): sheathed, the hostile slots are greyed with
    their reason and X draws; a press the rules refuse is noted in their words and flashes its
    slot; a held guard shows held; the tooltip names the slot and why it is greyed."""
    s = "bar"
    plan = ("ready;wait:2;cursor:0.5,0.3;wait:0.3;shot:01_sheathed;dump:01;cursor:@bar:Primary;wait:0.5;shot:02_tip;dump:02;"
            "cursor:0.5,0.3;key:KeyX:tap;wait:0.6;shot:03_drawn;dump:03;tap;wait:0.4;shot:04_refused;dump:04;wait:0.6;"
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


SCENARIOS = {"windows": windows, "talk": talk, "items": items, "themes": themes, "pick": pick, "turns": turns, "bar": bar, "offers": offers, "support": support}


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
