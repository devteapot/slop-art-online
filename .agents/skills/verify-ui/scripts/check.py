#!/usr/bin/env python3
"""Run verify-ui scenarios on a verify-ui-* world and check what they did.

  check.py --run RUN [SCENARIO ...]      default: the ordinary island scenarios
  check.py --list                        the scenarios, in the order they are defined (* needs Cullet)
  LIVING_GAME_THEME=night check.py …     the same in a theme (evidence in <scenario>-<theme>/)

Each scenario drives the real client headless through drive.py (one client run per scenario),
then checks the game UI's dumps (`dump:` steps: open windows, anchors, rectangles, the box and
whom it addresses, the weapon), the client log (what was sent through the player reducers) and,
for items, the authority's rows (owner SQL through verify.py). It prints PASS or FAIL per check
and writes `.local/living/verify/RUN/ui/checks.json`. Exit 1 when any check fails.

Two residents are placed beside the player and held still for the talk and items scenarios
(admin `place_at` and `set_behavior`: scene setup, not player acts).
"""
import argparse, glob, json, math, os, re, subprocess, sys, time
from contextlib import contextmanager

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "../../../.."))
V = os.path.join(ROOT, ".agents/skills/verify/scripts/verify.py")
sys.path.insert(0, os.path.dirname(V))
import verify
from drive import next_sync_wait
sys.path.insert(0, os.path.join(ROOT, "living/tools"))
from law_values import own_laws

W, H = 1600, 900


# The scenarios, by name, in the order they are defined below: each registers itself with
# @scenario. CULLET: those the default run leaves out, because they need a Cullet world.
SCENARIOS = {}
CULLET = set()
EXPLICIT = set()
# FRESH: scenarios that launch their own world under the run's name (no world may exist yet).
FRESH = set()


def scenario(name, cullet=False, explicit=False, fresh=False):
    def register(function):
        assert name not in SCENARIOS, f"scenario {name} registered twice"
        SCENARIOS[name] = function
        if cullet:
            CULLET.add(name)
        if explicit:
            EXPLICIT.add(name)
        if fresh:
            FRESH.add(name)
            EXPLICIT.add(name)
        return function
    return register


def sql(run, q, *, check=False):
    r = subprocess.run([sys.executable, V, "sql", "--run", run, q], capture_output=True, text=True)
    if check and r.returncode:
        raise RuntimeError(r.stderr.strip())
    t = r.stdout
    i = t.find("[")
    return json.loads(t[i:]) if i >= 0 else []


def sql_as_player(run, q):
    """SQL as verify.py's player identity (`$V player join`), through its views."""
    r = subprocess.run([sys.executable, V, "sql", "--run", run, q, "--as-player"], capture_output=True, text=True)
    t = r.stdout
    i = t.find("[")
    return json.loads(t[i:]) if i >= 0 else []


def call_admin(run, reducer, args, *, check=False):
    """An admin reducer call (scene setup or restore), its output for evidence."""
    r = subprocess.run([sys.executable, V, "call", "--run", run, reducer, json.dumps(args), "--as-admin"], capture_output=True, text=True)
    output = r.stdout + r.stderr
    if check and r.returncode:
        raise RuntimeError(output.strip())
    return output


def residents(run, n=2):
    """Adults the scene can place beside the player: alive people with a mind, not players."""
    rows = sql(run, "SELECT id, name, stage, alive, kind FROM character WHERE kind = 'person'")
    rows = [r for r in rows if r.get("alive") and r.get("stage") == 2 and r.get("name") not in ("Verifier",)]
    rows.sort(key=lambda r: r["id"])
    return [r["id"] for r in rows[:n]]


@contextmanager
def resident_fixture(run, ids):
    """Borrow residents for a scene and release their temporary position and graph."""
    where = " OR ".join(f"id = {actor}" for actor in ids)
    bodies = {r["id"]: r for r in sql(run, f"SELECT id, x, y FROM body WHERE {where}")}
    graphs = {r["id"]: r["graph"] for r in sql(run, f"SELECT id, graph FROM brain WHERE {where}")}
    if any(actor not in bodies or actor not in graphs for actor in ids):
        raise RuntimeError(f"could not snapshot body and brain for fixture residents {ids}")
    try:
        yield
    finally:
        errors = []
        # Return everyone to their tiles before waking the original behavior graphs.
        calls = [("place_at", [actor, bodies[actor]["x"], bodies[actor]["y"]]) for actor in ids]
        calls += [("set_behavior", [actor, graphs[actor]]) for actor in ids]
        for reducer, args in calls:
            try:
                call_admin(run, reducer, args, check=True)
            except RuntimeError as error:
                errors.append(f"{reducer} for resident #{args[0]}: {error}")
        if errors:
            raise RuntimeError("resident fixture restore failed:\n" + "\n".join(errors))


@contextmanager
def sight_fixture(run, defaults):
    """Restore scene daylight and sight laws, including laws compiled into the seed."""
    original = own_laws(lambda q: sql(run, q))
    epoch = sql(run, "SELECT epoch_ms FROM world")[0]["epoch_ms"]
    try:
        yield
    finally:
        try:
            for law, default in defaults.items():
                call_admin(run, "set_world_law", [law, original.get(law, default)], check=True)
        finally:
            sql(run, f"UPDATE world SET epoch_ms = {epoch} WHERE id = 0", check=True)


# These four laws are enabled in Cullet's authored script before any override exists.
CULLET_SIGHT = dict.fromkeys(("gaze_on", "fov_on", "cover_sight_on", "cover_brush_on"), "true")


THEME = os.environ.get("LIVING_GAME_THEME", "")
BEARING = float(os.environ.get("VERIFY_UI_BEARING", "0")) % 360
BEARING_SUFFIX = f"-bearing-{BEARING:g}" if BEARING else ""


def bearing_offset(x, y):
    angle = math.radians(BEARING)
    return (x * math.cos(angle) - y * math.sin(angle),
            x * math.sin(angle) + y * math.cos(angle))


def at_bearing(d, expected=BEARING):
    yaw = view(d).get("yaw")
    return yaw is not None and abs((yaw - expected + 180) % 360 - 180) < 0.05


def drive(run, name, plan, places=(), syncs=(), extra=(), free=(), env=None):
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
    r = subprocess.run(cmd, capture_output=True, text=True, env=dict(os.environ, **env) if env else None)
    # Check the live authority before interpreting any captured perception as a UI result.
    verify.require_running(verify.load(run), verify.admin_token())
    out = os.path.join(ROOT, ".local/living/verify", run, "ui", name)
    return out, r.returncode, r.stdout + r.stderr


def dump(out, name):
    p = os.path.join(out, f"{name}.json")
    return json.load(open(p)) if os.path.exists(p) else None


def log(out):
    p = os.path.join(out, "client.log")
    return re.sub(r"\x1b\[[0-9;]*m", "", open(p, errors="replace").read()) if os.path.exists(p) else ""


def partition_sync(text, name, *, last=False):
    """Split at an exact live-script sync step name."""
    matches = list(re.finditer(rf"live script: sync:{re.escape(name)}(?= \(me )", text))
    if not matches:
        return ("", "", text) if last else (text, "", "")
    match = matches[-1] if last else matches[0]
    return text[:match.start()], match[0], text[match.end():]


def fresh_log(out):
    """Remove a drive's earlier client.log (a scenario run again under the same run), so a wait
    on the log for a sync can only match the new client's lines."""
    p = os.path.join(out, "client.log")
    if os.path.exists(p):
        os.remove(p)


def cutaway_fades(text, folder):
    """Return the fading asset paths from this exact directory."""
    files = re.findall(r"cutaway: (\S+) fades to ", text)
    return [file for file in files if os.path.basename(os.path.dirname(file)) == folder]


class Checks:
    def __init__(self):
        self.rows = []

    def check(self, scenario, what, ok, detail=""):
        self.rows.append({"scenario": scenario, "check": what, "ok": bool(ok), "detail": detail})
        print(f"{'PASS' if ok else 'FAIL'}  {scenario}: {what}{('  (' + detail + ')') if detail and not ok else ''}", flush=True)


def notes_clear(c, s, out):
    """Notes and the F prompt never overlap (note-place-1): in every dump of the drive where both
    show (`rects` in the dump, UI px), their rectangles do not intersect."""
    both, hit = 0, []
    for f in sorted(glob.glob(os.path.join(out, "*.json"))):
        try:
            r = (json.load(open(f)) or {}).get("rects") or {}
        except (ValueError, OSError, AttributeError):
            continue
        p, ns = r.get("prompt"), r.get("notes") or []
        if not p or not ns:
            continue
        both += 1
        for n in ns:
            if p[0] < n[0] + n[2] and n[0] < p[0] + p[2] and p[1] < n[1] + n[3] and n[1] < p[1] + p[3]:
                hit.append((os.path.basename(f), [round(x) for x in p], [round(x) for x in n]))
    c.check(s, "notes and the F prompt never overlap while both show", not hit, f"{both} dumps with both; overlapping {hit}")
    return both


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


@scenario("windows")
def windows(run, c):
    s = "windows" + BEARING_SUFFIX
    plan = (f"ready;yaw:{BEARING};wait:2;shot:01_explore;dump:01;click:@menu;wait:0.4;shot:02_menu;dump:02;click:@menu:Settings;wait:0.5;shot:03_settings;dump:03;"
            "key:KeyI:tap;wait:0.4;key:KeyL:tap;wait:0.5;shot:04_log_pack;dump:04;slide:@win:Log:head>0.62,0.45:0.6;wait:0.2;shot:05_dragging;"
            "wait:0.5;shot:06_swapped;dump:06;click:@win:Pack:close;wait:0.4;dump:07;key:KeyI:tap;wait:0.4;dump:08;key:Escape:tap;wait:0.3;dump:09;key:Escape:tap;wait:0.3;dump:10;"
            "key:Escape:tap;wait:0.4;shot:11_esc_menu;dump:11;key:Escape:tap;wait:0.3;dump:12;quit")
    out, code, text = drive(run, s, plan)
    c.check(s, "client ran and joined", code == 0, text[-300:])
    notes_clear(c, s, out)
    d = {k: dump(out, k) for k in ["01", "02", "03", "04", "06", "07", "08", "09", "10", "11", "12"]}
    c.check(s, "requested bearing is shown", at_bearing(d["01"]), repr(view(d["01"])))
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


def utc_ms(line):
    """The client log line's UTC time (ms since the epoch), from its leading ISO stamp."""
    import datetime
    m = re.match(r"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(\.\d+)?Z", line)
    if not m:
        return None
    t = datetime.datetime.strptime(m[1], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=datetime.timezone.utc).timestamp()
    return int((t + float(m[2] or 0)) * 1000)


@scenario("preparing", fresh=True)
def preparing(run, c):
    """Staged genesis (docs/STAGED_GENESIS.md §4, living/game/src/genesis.rs): the client joins a
    world still being made. The scenario launches the run's island world itself (`verify.py
    launch`, which waits for genesis through genesis_wait.py) and starts the client as soon as the
    publish is under way, so it connects while the world is made: the cover says "Preparing the
    world…" with the step, the steps and a bar, nothing is shown as a failure, and the client
    joins once `genesis.done` turns true. Beside it, a probe `join` as verify.py's player
    identity records the authority's refusal text while the world is made. Run it on a run name
    with no world yet (`check.py --run ui-<new> preparing`), then `cleanup`."""
    sys.path.insert(0, os.path.join(ROOT, "living/tools"))
    import genesis_wait
    s = "preparing"
    st = verify.load(run)
    if st.get("published") or st.get("publish_attempted"):
        c.check(s, "a run name with no world yet", False, f"verify-{run} was already launched; use a new run name")
        return
    out = os.path.join(ROOT, ".local/living/verify", run, "ui", s)
    os.makedirs(out, exist_ok=True)
    seed = os.environ.get("VERIFY_UI_PREPARING_SEED", "island")
    target = os.environ.get("VERIFY_UI_TARGET_DIR", os.path.join(ROOT, ".local/living/verify", run, "target"))
    launch_log = open(os.path.join(out, "launch.log"), "w")
    launch = subprocess.Popen([sys.executable, V, "launch", "--run", run, "--seed", seed, "--target-dir", target], stdout=launch_log, stderr=subprocess.STDOUT, cwd=ROOT)
    # The client goes as soon as the publish is under way (the module is built): it cannot reach
    # the world for a moment, tries again every 3 s, and gets in while the world is being made.
    state = os.path.join(ROOT, ".local/living/verify", run, "state.json")
    while launch.poll() is None and not (os.path.exists(state) and json.load(open(state)).get("publish_attempted")):
        time.sleep(0.2)
    if launch.poll() not in (None, 0):
        c.check(s, "the world launched", False, open(os.path.join(out, "launch.log")).read()[-600:])
        return
    plan = ("preparing:180;wait:0.5;shot:01_preparing;dump:01;wait:3;shot:02_preparing;dump:02;"
            "ready;wait:1;shot:03_joined;dump:03;quit")
    cmd = [sys.executable, os.path.join(HERE, "drive.py"), "--run", run, "--name", s, "--plan", plan, "--timeout", "600", "--preparing"]
    client = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    # Meanwhile, the authority's side: the `genesis` row as it goes, and one probe `join` while
    # the world is still being made (verify.py's player identity; refused, so nothing is made).
    samples, probe, owner = [], None, None
    while client.poll() is None:
        st = verify.load(run)
        if st.get("published"):
            owner = owner or verify.admin_token()
            try:
                row = genesis_wait.genesis_row(verify.URL, st["db"], owner)
            except genesis_wait.GenesisNotReady:
                row = None
            if row is not None and (not samples or (samples[-1]["step"], samples[-1]["done"]) != (row["step"], row["done"])):
                samples.append({"wall_ms": int(time.time() * 1000), "step": row["step"], "steps": row["steps"], "label": row["label"], "done": row["done"], "updated_ms": row["updated_ms"]})
            if row is not None and not row["done"] and probe is None:
                r = subprocess.run([sys.executable, V, "player", "--run", run, "join", "Probe"], capture_output=True, text=True)
                probe = {"code": r.returncode, "out": (r.stdout + r.stderr).strip()[-400:]}
        time.sleep(0.25)
    text_out = client.stdout.read()
    code = client.wait()
    launch.wait()
    launch_log.close()
    final = None
    if owner:
        try:
            final = genesis_wait.genesis_row(verify.URL, f"verify-{run}", owner)
        except genesis_wait.GenesisNotReady:
            pass
    json.dump({"genesis": samples, "final": final, "probe": probe}, open(os.path.join(out, "genesis.json"), "w"), indent=1)
    c.check(s, "the world launched and was made", launch.returncode == 0 and final and final.get("done"), open(os.path.join(out, "launch.log")).read()[-400:])
    c.check(s, "client ran and joined", code == 0, text_out[-300:])
    c.check(s, "the authority refuses join while the world is made, with world_preparing",
            probe is not None and re.search(r"world_preparing: the world is still being made \(step \d+ of \d+: [^)]*", probe["out"]), repr(probe))
    t = log(out)
    d1, d2, d3 = dump(out, "01"), dump(out, "02"), dump(out, "03")
    g1, g2, g3 = ((d or {}).get("genesis") or {} for d in (d1, d2, d3))
    cover = g1.get("cover") or {}
    progress = g1.get("progress") or {}
    c.check(s, "the client saw the world being made", g1.get("gate") == "Preparing" and ("genesis: the world is being made" in t or "genesis: preparing step" in t), json.dumps(g1)[:300])
    c.check(s, "the cover says Preparing the world… with the step, the steps and a bar",
            cover.get("title") == "Preparing the world…" and progress.get("steps", 0) > 0 and cover.get("bar") is not None
            and f"step {progress.get('step')} of {progress.get('steps')}" in (cover.get("detail") or ""), json.dumps(cover))
    p2 = g2.get("progress") or {}
    c.check(s, "the progress line moves while the world is made", g2.get("gate") != "Preparing" or (p2.get("step", 0), p2.get("label")) != (progress.get("step", 0), progress.get("label")),
            f"{progress} -> {p2}")
    c.check(s, "joined after the world was ready", "genesis: the world is ready after" in t and re.search(r"playing character #\d+", t) and g3.get("gate") == "Ready" and not g3.get("cover"), json.dumps(g3)[:300])
    held = [e for d in (d1, d2, d3) for e in ((d or {}).get("genesis") or {}).get("errors", [])]
    notes = [n for d in (d1, d2, d3) for n in (d or {}).get("notes", [])]
    c.check(s, "no error shown: world_preparing never lands in the errors, the notes or a warning",
            not held and not [n for n in notes if "world_preparing" in n] and not re.search(r"WARN.*(world_preparing|join refused)", t), f"errors {held}; notes {notes}")
    m = re.search(r"genesis: joined ([\d.]+) s after the world was ready", t)
    joined_line = next((l for l in t.splitlines() if re.search(r"playing character #\d+", l)), "")
    # When the authority's world turned ready: the first owner read that saw `done` (polled every
    # 0.25 s, so up to about 0.3 s late). Not `genesis.updated_ms`: the last step stamps it when
    # it starts, and populate runs about 4 s on the island after that.
    done_ms = next((x["wall_ms"] for x in samples if x["done"]), None)
    joined_ms = utc_ms(joined_line)
    gap = (joined_ms - done_ms) / 1000 if done_ms and joined_ms else None
    stamp = (done_ms - final["updated_ms"]) / 1000 if done_ms and final else None
    detail = (f"client: {m[1] if m else '?'} s from seeing done to playing; authority done (first owner read of done) to the client's 'playing character': "
              f"{gap if gap is None else round(gap, 2)} s; that read came {stamp if stamp is None else round(stamp, 2)} s after the done row's updated_ms")
    print(f"      {detail}", flush=True)
    c.check(s, "joined within 10 s of done", gap is not None and 0 <= gap < 10, detail)
    json.dump({"client_done_to_join_s": float(m[1]) if m else None, "authority_done_to_join_s": gap, "done_seen_ms": done_ms, "done_updated_ms": final and final.get("updated_ms"), "joined_ms": joined_ms}, open(os.path.join(out, "timing.json"), "w"), indent=1)


@scenario("bubble-once")
def bubble_once(run, c):
    """A line is shown once per speech row (play-test 6: Sissly's long reply came back as a bubble
    7.6 s after it was said, once her short line said 2.1 s later had gone; no new row behind it).
    A resident beside a fresh player says a long line (a 10 s bubble), then a short one 2.1 s
    later (about 5 s), both admin `mind_say` to the player. The dumps follow A's bubble: the long
    line, then the short one, then nothing at 8.5 s, while the long line's own life (10 s) would
    still run."""
    s = "bubble-once"
    a = residents(run, 1)[0]
    long = "It's just past the berry bushes! Come on, but walk slow, my legs are little. I like crust too, we can share the crusty edges."
    short = "You never said! Crust or filling?"
    thought = json.dumps({"kind": "talk", "summary": "", "detail": "", "latency_ms": 0, "tokens": 0, "model": "verify-ui scene", "reference": ""})
    syncs = [f'one=mind_say|{a}|"{long}"|{{me}}|""|0|{thought}', f'two=mind_say|{a}|"{short}"|{{me}}|""|0|{thought}']
    plan = ("ready;sync:scene;wait:2.5;sync:one;wait:1.0;dump:b1;wait:1.1;sync:two;wait:0.9;dump:b2;wait:3.2;dump:b3;wait:2.2;shot:01_after;dump:b4;wait:1.5;dump:b5;quit")
    tok = os.path.join(ROOT, ".local/living/verify", run, "ui", f"bubble-once-{int(time.time())}.token")
    out, code, text = drive(run, s, plan, places=[f"{a}:2:0"], syncs=syncs, extra=["--token", tok, "--player", "Listener"])
    c.check(s, "client ran and joined (a fresh player)", code == 0, text[-300:])
    over = lambda k: [x.get("text") for x in (dump(out, k) or {}).get("bubbles") or [] if x.get("speaker") == a]
    seq = {k: over(k) for k in ("b1", "b2", "b3", "b4", "b5")}
    c.check(s, "the long line shows, then the short one in its place", seq["b1"] == [long] and seq["b2"] == [short], str(seq))
    c.check(s, "once the short line's bubble ends, the long line does not show again", seq["b4"] == [] and seq["b5"] == [] and long not in (seq["b3"] + seq["b4"] + seq["b5"]), str(seq))
    rows = [r for r in sql(run, f"SELECT id, kind, subject, text FROM experience WHERE kind = 'speech' AND subject = {a}") if long in r.get("text", "")]
    c.check(s, "one speech row behind the long line for the player", len([r for r in rows]) >= 1, f"{len(rows)} rows")


@scenario("room-detail")
def room_detail(run, c):
    """speech-address in the client: how a line to the room was said ("to the room, naming you
    and a stranger") shows beside the speaker in the Log and their window, in the player's own
    labels; the bubble keeps the words only; a line to someone gets no detail. A fresh player
    ("Listener") with two residents held beside it; A says to the room a line naming B (by B's
    given name) and the player (admin `mind_say`, the speech minds use), then a line to the player.
    talk-turns: then A says to B a line that names the player ("Ask Listener …"): the authority's
    row says ", naming you" after the addressee, and the Log and A's window show "A (to B, naming
    you)" with B in the player's own label; the bubble keeps the words only."""
    s = "room-detail"
    a, b = residents(run)
    names = {r["id"]: r.get("name", "") for r in sql(run, "SELECT id, name FROM character WHERE kind = 'person'")}
    first = (names.get(b) or "").split(" ")[0]
    words = f"Come and look, {first} and Listener!"
    thought = json.dumps({"kind": "talk", "summary": "", "detail": "", "latency_ms": 0, "tokens": 0, "model": "verify-ui scene", "reference": ""})
    other = "Ask Listener, she will know."
    syncs = [f'room=mind_say|{a}|"{words}"|0|""|0|{thought}', f'tome=mind_say|{a}|"Just you, now."|{{me}}|""|0|{thought}',
             f'toother=mind_say|{a}|"{other}"|{b}|""|0|{thought}']
    plan = ("ready;sync:scene;wait:2.5;sync:room;wait:1.2;shot:01_bubble;dump:01;key:KeyL:tap;wait:0.6;shot:02_log;dump:02;key:KeyL:tap;wait:0.3;"
            f"menu:f@id:{a};wait:0.5;click:@acts:0:window;wait:0.6;shot:03_window;dump:03;sync:tome;wait:1.5;shot:04_to_me;dump:04;"
            "sync:toother;wait:1.2;shot:05_to_other;dump:05;key:KeyL:tap;wait:0.6;shot:06_log;dump:06;key:KeyL:tap;wait:0.3;quit")
    tok = os.path.join(ROOT, ".local/living/verify", run, "ui", f"room-detail-{int(time.time())}.token")
    out, code, text = drive(run, s, plan, places=[f"{a}:2:0", f"{b}:-2:0"], syncs=syncs, extra=["--token", tok, "--player", "Listener"])
    c.check(s, "client ran and joined (a fresh player)", code == 0, text[-300:])
    d = {k: dump(out, k) or {} for k in ("01", "02", "03", "04", "05", "06")}
    lines = lambda k: (d[k].get("extra") or {}).get("lines") or []
    room = next((l for l in lines("02") if l.get("speaker") == a and l.get("to") == 0 and l.get("text") == words), None)
    how = (room or {}).get("how") or ""
    c.check(s, "the room line carries how it was said, naming you and the other as I know them", how.startswith("to the room, ") and "you" in how and "stranger" in how and first not in how and "Listener" not in how, f"{how!r}; lines {lines('02')[-3:]}")
    c.check(s, "its words stay the words alone", room is not None and room.get("text") == words, str(room))
    bub = [x.get("text") for x in d["01"].get("bubbles") or [] if x.get("speaker") == a]
    c.check(s, "the bubble over them shows the words only", bub == [words], str(bub))
    c.check(s, "their window is open on the same lines", f"Person{a}" in [w for w, _ in wins(d["03"])], str(wins(d["03"])))
    tome = next((l for l in lines("04") if l.get("speaker") == a and l.get("text") == "Just you, now."), None)
    c.check(s, "a line to me carries no detail", tome is not None and not tome.get("how"), str(tome))
    # talk-turns: a line to B that names me (and any earlier run's "Listener", an offline player
    # character still standing here: "naming a stranger and you").
    sc = json.load(open(os.path.join(out, "scene.json"))) if os.path.exists(os.path.join(out, "scene.json")) else {}
    me = sc.get("me")
    row = next((r for r in sql(run, f"SELECT id, text FROM experience WHERE observer = {me} AND kind = 'speech' AND subject = {a} AND object = {b}") if other in r.get("text", "")), None) if me else None
    c.check(s, "to B naming me: the authority's row says so after the addressee", row is not None and ", naming " in row.get("text", "") and "you: “" in row.get("text", "") and first not in row.get("text", ""), str(row))
    named = next((l for l in lines("06") if l.get("speaker") == a and l.get("to") == b and l.get("text") == other), None)
    c.check(s, "to B naming me: the line keeps the detail, the words alone", named is not None and (named.get("how") or "").startswith(", naming ") and named["how"].endswith("you"), str(named))
    # The head as the window and the Log show it (`people::line_head`), B as the window labels them.
    head_w = next((l.get("head_window") for l in lines("05") if l.get("speaker") == a and l.get("text") == other), None) or ""
    head_l = (named or {}).get("head") or ""
    c.check(s, "to B naming me: A's window shows it beside them, B in my own label", ", naming " in head_w and head_w.endswith("you)") and " (to " in head_w and first not in head_w, f"{head_w!r}; window names {[t for w, t in d['05'].get('naming') or [] if w == 'window']}")
    c.check(s, "to B naming me: the Log shows it too", ", naming " in head_l and head_l.endswith("you)") and " (to " in head_l and first not in head_l, repr(head_l))
    bub = [x.get("text") for x in d["05"].get("bubbles") or [] if x.get("speaker") == a]
    c.check(s, "to B naming me: the bubble shows the words only", bub == [other], str(bub))


@scenario("move-off")
def move_off(run, c):
    """talk-turns' `moved` code and `on_the_move` in the client. At noon on open grass, cleared, a
    fresh player ("Mover") beside a resident held 2.5 m off: it looks them over (`appraise`, 1.5 s)
    and walks off 0.4 s later: the authority breaks it off with code `moved` and the rules'
    sentence ("The look stopped: you moved off before it was done."), which shows once, as a quiet
    note (not a failure). Then it waves at them and walks on 0.4 s later, the play-test 6 case: the
    wave (`on_the_move`) is not broken off, and the client keeps drawing it while the body walks."""
    s = "move-off"
    (a,) = residents(run, 1)
    people = {r["id"] for r in sql(run, "SELECT id, kind FROM character WHERE kind = 'person'")}
    ax, ay = UNHEARD_SPOT
    for i, r in enumerate(x for x in sql(run, "SELECT id, x, y FROM body") if x["id"] in people and x["id"] != a and ((x["x"] - ax) ** 2 + (x["y"] - ay) ** 2) ** 0.5 < 25):
        call_admin(run, "place_at", [r["id"], ax + 40, ay + 3 * i])
    tok = os.path.join(ROOT, ".local/living/verify", run, "ui", f"move-off-{int(time.time())}.token")
    syncs = ["noon=sql|UPDATE world SET epoch_ms = {epoch_at:12} WHERE id = 0", f"spot=place_at|{{me}}|{ax}|{ay}"]
    plan = ("ready;sync:noon;sync:spot;wait:2;sync:scene;wait:2.5;dump:m0;"
            f"gesture:appraise:{a};wait:0.4;key:KeyW:down;wait:0.8;key:KeyW:up;wait:0.6;shot:01_moved;dump:m1;wait:2.5;dump:m2;"
            f"wait:1.5;dump:w0;gesture:wave:{a};wait:0.4;key:KeyW:down;wait:0.4;dump:w1;wait:0.5;shot:02_waving;dump:w2;wait:0.3;key:KeyW:up;wait:1.5;dump:w3;quit")
    out, code, text = drive(run, s, plan, places=[f"{a}:2.5:0"], syncs=syncs, extra=["--token", tok, "--player", "Mover"])
    c.check(s, "client ran and joined (a fresh player)", code == 0, text[-300:])
    sc = json.load(open(os.path.join(out, "scene.json"))) if os.path.exists(os.path.join(out, "scene.json")) else {}
    me = sc.get("me")
    d = {k: dump(out, k) or {} for k in ("m0", "m1", "m2", "w0", "w1", "w2", "w3")}
    rows = sql(run, f"SELECT id, ok, skill, code, why, at_ms FROM act_outcome WHERE observer = {me} AND kind = 'act'") if me else []
    moved = [r for r in rows if r.get("code") == "moved"]
    c.check(s, "the look broken off by my move: one act_outcome, code moved, in the rules' words", len(moved) == 1 and moved[0].get("skill") == "appraise" and "moved off before it was done" in moved[0].get("why", ""), str(rows)[:600])
    said = "moved off before it was done"
    notes = lambda k: list(zip(d[k].get("notes") or [], d[k].get("note_ok") or []))
    n1 = [(t, ok) for t, ok in notes("m1") if said in t]
    c.check(s, "its words show once, as a quiet note (not a failure, not unknown)", len(n1) == 1 and n1[0][1] is None and n1[0][0].lower().startswith("the look stopped"), str(notes("m1")))
    c.check(s, "and not again", all(len([t for t, _ in notes(k) if said in t]) <= 1 for k in ("m2", "w0", "w1", "w2", "w3")), str([notes(k) for k in ("m2", "w3")]))
    ev = [e for e in ((d["m2"].get("extra") or {}).get("events") or []) if said in e]
    c.check(s, "the Log's events tell it once", len(ev) == 1, str((d["m2"].get("extra") or {}).get("events")))
    waves = [r for r in rows if r.get("skill") == "wave"]
    c.check(s, "the wave, walked on from, is not broken off (on_the_move)", bool(waves) and all(r.get("code") != "moved" for r in waves) and any(r.get("ok") for r in waves), str(waves))
    at = lambda k: (d[k].get("me_at") or {}).get("drawn")
    dist = lambda k: ((at(k)[0] - at("w0")[0]) ** 2 + (at(k)[1] - at("w0")[1]) ** 2) ** 0.5 if at(k) and at("w0") else 0.0
    once = lambda k: ((d[k].get("extra") or {}).get("onces") or {}).get(str(me))
    c.check(s, "the client keeps drawing the wave while the body walks on", once("w1") == "wave" and once("w2") == "wave" and dist("w2") > 0.5, f"onces {once('w1')!r} {once('w2')!r}; walked {dist('w1'):.2f} m, {dist('w2'):.2f} m")
    bad = [(t, ok) for k in ("w1", "w2", "w3") for t, ok in notes(k) if ok is False]
    c.check(s, "no failure note for the wave", not bad, str(bad))


@scenario("earshot")
def earshot(run, c):
    """The authority's earshot in the client (the `earshot` law, on as shipped since earshot-on): with it on, the
    talk box takes whom Tab goes to, and their order, from `my_earshot`'s `say` list, and shows its
    sentence (in my own labels) in the box's hint line; someone who steps out of a say's reach
    drops from it while a call still reaches them. With it off: no row, the client's own reckoning,
    as before. Face both residents at noon on open grass so the Call list proves B stayed
    visible after leaving Say range."""
    s = "earshot"
    cards = {r["name"]: r["carry_m"] for r in sql(run, "SELECT name, carry_m FROM speech_card")}
    carry, call_carry = cards.get("say", 0), cards.get("call", 0)
    if not 0 < carry < call_carry:
        c.check(s, "world speech cards give Say and a wider Call", False, str(cards))
        return
    print(f"{s}: Say carry {carry:g} m; Call carry {call_carry:g} m", flush=True)
    # The card already applies carry_for to ordinary world hearing. Leave enough room
    # for tile snapping while keeping B within the base island's short daytime sight.
    away = min(1.1 * carry, (carry + call_carry) / 2)
    a, b = residents(run)
    # Anyone within 25 m of the spot (offline player characters of earlier drives among them) is
    # put 40 m east first: they would stand in every list.
    people = {r["id"] for r in sql(run, "SELECT id, kind FROM character WHERE kind = 'person'")}
    ax, ay = UNHEARD_SPOT
    for i, r in enumerate(x for x in sql(run, "SELECT id, x, y FROM body") if x["id"] in people and x["id"] not in (a, b) and ((x["x"] - ax) ** 2 + (x["y"] - ay) ** 2) ** 0.5 < 25):
        call_admin(run, "place_at", [r["id"], ax + 40, ay + 3 * i])
    tok = os.path.join(ROOT, ".local/living/verify", run, "ui", f"earshot-{int(time.time())}.token")
    syncs = ["noon=sql|UPDATE world SET epoch_ms = {epoch_at:12} WHERE id = 0", f"spot=place_at|{{me}}|{ax}|{ay}",
             'on=set_world_law|"earshot"|"true"', f"away=place_at|{b}|(mx+{away})|(my+1)",
             "senses=client_sql|SELECT hearing, sight FROM my_senses",
             'off=set_world_law|"earshot"|"false"']
    plan = ("ready;sync:noon;sync:spot;wait:2;sync:on;sync:scene;look:90;wait:3;sync:senses;key:Enter:tap;wait:1.2;shot:01_box;dump:e1;tab;wait:0.4;dump:t1;tab;wait:0.4;dump:t2;tab;wait:0.4;dump:t3;"
            "key:Escape:tap;wait:0.3;sync:away;wait:2;key:Enter:tap;wait:1.2;shot:02_away;dump:e2;tab;wait:0.4;dump:t4;tab;wait:0.4;dump:t5;key:Escape:tap;wait:0.3;"
            "sync:off;wait:2;key:Enter:tap;wait:1.2;shot:03_off;dump:e3;tab;wait:0.4;dump:t6;key:Escape:tap;wait:0.3;quit")
    try:
        out, code, text = drive(
            run, s, plan, places=[f"{a}:{0.6 * carry}:0", f"{b}:{0.8 * carry}:1"],
            syncs=syncs, extra=["--token", tok, "--player", "Hearer"],
            env={"LIVING_GAME_CONTROL": "cursor"},
        )
    finally:
        # Back to the shipped law (on).
        call_admin(run, "set_world_law", ["earshot", "true"])
    scene = dump(out, "scene") or {}
    snapshots = scene.get("snaps", {}).get("senses", [])
    senses = snapshots[0]["rows"] if snapshots else []
    ranges = f"Say carry {carry:g} m; Call carry {call_carry:g} m; my_senses {senses}"
    c.check(s, "client ran and joined (a fresh player)", code == 0 and bool(senses), f"{ranges}; {text[-300:]}")
    d = {k: dump(out, k) or {} for k in ("e1", "t1", "t2", "t3", "e2", "t4", "t5", "e3", "t6")}
    ty = lambda k: d[k].get("typing") or {}
    told = lambda k: ty(k).get("told") or {}
    ways = lambda k: {w: h for w, h in told(k).get("ways") or []}
    say1 = ways("e1").get("say")
    c.check(s, "law on: the box's earshot is the authority's say list, both residents in it", say1 is not None and ty("e1").get("earshot") == say1 and a in say1 and b in say1, f"say {say1}; box {ty('e1').get('earshot')}; ways {ways('e1')}")
    c.check(s, "law on: the sentence is given, in my own labels", bool(told("e1").get("text")) and "earshot" in told("e1").get("text", "").lower(), repr(told("e1").get("text")))
    # Each press against the list it went by (`typing.tab`): the authority's say list at that
    # moment, the next after the last, the room after the last of them (others than A and B may
    # stand within a say's reach too).
    def nxt(prev, e):
        if not e:
            return prev
        if prev in e:
            i = e.index(prev)
            return e[i + 1] if i + 1 < len(e) else None
        return e[0]
    def steps(keys):
        out = []
        for k in keys:
            tb = ty(k).get("tab") or {}
            say = ways(k).get("say")
            # Whether the press went by the authority's list (the client records it at the press:
            # the row is rewritten up to four times a second and people walk in and out of reach,
            # so a later dump's list may differ), and the step by that same list.
            out.append((tb.get("authority") is True, tb.get("chose") == nxt(tb.get("prev"), tb.get("earshot") or []), tb.get("prev"), tb.get("chose"), tb.get("earshot")))
        return out
    st = steps(("t1", "t2", "t3"))
    c.check(s, "law on: each Tab goes by the authority's say list, in its order", all(x[0] and x[1] for x in st), str(st))
    say2, call2 = ways("e2").get("say"), ways("e2").get("call")
    c.check(s, "B steps beyond Say range and stays visible in Call range", say2 is not None and b not in say2 and a in say2 and call2 is not None and b in call2 and ty("e2").get("earshot") == say2, f"say {say2}; call {call2}; box {ty('e2').get('earshot')}")
    st2 = steps(("t4", "t5"))
    c.check(s, "Tab then goes by the new say list and never to B", all(x[0] and x[1] for x in st2) and all(b not in (x[4] or []) and x[3] != b for x in st2), str(st2))
    c.check(s, "law off: no row, the client's own reckoning (A within it)", not ty("e3").get("told") and a in (ty("e3").get("earshot") or []), f"told {ty('e3').get('told')}; earshot {ty('e3').get('earshot')}")
    t6 = ty("t6").get("tab") or {}
    c.check(s, "law off: Tab as before, by the client's own reckoning", t6.get("authority") is False and t6.get("chose") == nxt(t6.get("prev"), t6.get("earshot") or []), str(t6))


@scenario("ways")
def ways(run, c):
    """The world's ways of speaking in the talk box (`speech_card`; `human_speak`): the chip shows
    the box's way, the Way key (Up) moves to the next in the cards' order; a line goes in that
    way; Tab follows its reach; its `max_chars` cuts the box; what the rules refuse comes back in
    their words, once. At noon on open grass, cleared, a fresh player with residents A 2 m off, C
    10 m off (beyond a say's 9 m, within sight: 11 m by day) and B 20 m off (beyond sight, within a
    call's reach): a say reaches A (Tab: A, not C); a whisper with no one within its reach is
    refused ("a whisper needs someone to whisper to"); a call's Tab holds A and C, and B, unseen,
    hears it. Then Settings › Controls offers the Way key."""
    s = "ways"
    cards = sorted(sql(run, "SELECT * FROM speech_card"), key=lambda r: (r.get("order", 0), r.get("name", "")))
    names = [r["name"] for r in cards]
    by = {r["name"]: r for r in cards}
    # The rules' whisper and call, by what they are (a way that needs someone within a reach; the
    # one that carries farthest), not by name.
    near = next((r for r in cards if r.get("needs_to") and r.get("reach_m", 0) > 0), None)
    far = max(cards, key=lambda r: r.get("carry_m", 0)) if cards else None
    c.check(s, "the world has ways of speaking: a close one that needs someone, and a far one", len(cards) >= 3 and near is not None and far is not None and far is not cards[0], str([(r["name"], r.get("order"), r.get("needs_to"), r.get("reach_m"), r.get("carry_m"), r.get("max_chars")) for r in cards]))
    if not (near and far):
        return
    a, b, cc = residents(run, 3)
    people = {r["id"] for r in sql(run, "SELECT id, kind FROM character WHERE kind = 'person'")}
    ax, ay = UNHEARD_SPOT
    for i, r in enumerate(x for x in sql(run, "SELECT id, x, y FROM body") if x["id"] in people and x["id"] not in (a, b, cc) and ((x["x"] - ax) ** 2 + (x["y"] - ay) ** 2) ** 0.5 < 30):
        call_admin(run, "place_at", [r["id"], ax - 45, ay + 3 * i])
    up = lambda n: "".join("key:ArrowUp:tap;wait:0.3;" for _ in range(n))
    to_near = names.index(near["name"])
    to_far = (names.index(far["name"]) - to_near) % len(names)
    long = ("Over here! " + "x" * 120)
    plan = ("ready;sync:noon;sync:spot;wait:2;sync:scene;wait:3;"
            "key:Enter:tap;wait:0.8;dump:s0;tab;wait:0.4;dump:s1;type:Good day to you.;enter;wait:2.5;"
            f"key:Enter:tap;wait:0.5;{up(to_near)}wait:0.6;shot:01_near;dump:w0;tab;wait:0.4;dump:w1;type:Psst.;enter;wait:2.5;dump:w2;"
            f"key:Enter:tap;wait:0.5;{up(to_far)}wait:0.6;dump:c0;type:{long};wait:0.4;shot:02_far;dump:c1;enter;wait:3;dump:c2;"
            "click:@menu;wait:0.4;click:@menu:Settings;wait:0.8;click:@settings:page:controls;wait:0.6;dump:k0;key:Escape:tap;wait:0.3;quit")
    tok = os.path.join(ROOT, ".local/living/verify", run, "ui", f"ways-{int(time.time())}.token")
    syncs = ["noon=sql|UPDATE world SET epoch_ms = {epoch_at:12} WHERE id = 0", f"spot=place_at|{{me}}|{ax}|{ay}"]
    out, code, text = drive(run, s, plan, places=[f"{a}:2:0", f"{cc}:0:10", f"{b}:20:0"], syncs=syncs, extra=["--token", tok, "--player", "Speaker"])
    c.check(s, "client ran and joined (a fresh player)", code == 0, text[-300:])
    d = {k: dump(out, k) or {} for k in ("s0", "s1", "w0", "w1", "w2", "c0", "c1", "c2", "k0")}
    ty = lambda k: d[k].get("typing") or {}
    way = lambda k: (ty(k).get("way") or {}).get("name")
    ear = lambda k: ty(k).get("earshot") or []
    c.check(s, "the box opens in the world's first way; its reach holds A, not C 10 m off nor B 20 m off", way("s0") == names[0] and a in ear("s0") and cc not in ear("s0") and b not in ear("s0"), f"way {way('s0')}; earshot {ear('s0')}")
    c.check(s, "Tab goes by that way's list", (ty("s1").get("tab") or {}).get("earshot") == ear("s1") and ty("s1").get("to") in ear("s1"), str(ty("s1").get("tab")))
    heard = lambda who, words: [r for r in sql(run, f"SELECT id, kind, text FROM experience WHERE observer = {who} AND kind = 'speech'") if words in r.get("text", "")]
    c.check(s, "the say reaches A as before", bool(heard(a, "Good day to you.")), "A's speech rows")
    c.check(s, "the Way key moves to the close way: no one within its reach, Tab has no one", way("w0") == near["name"] and ear("w0") == [] and ear("w1") == [], f"way {way('w0')}; earshot {ear('w0')}, {ear('w1')}")
    refusal = [n for n in d["w2"].get("notes") or [] if "whisper" in n.lower() or "needs someone" in n.lower()]
    c.check(s, "the close way to no one: refused in the rules' words, once", len(refusal) == 1, str(d["w2"].get("notes")))
    c.check(s, "the far way's Tab holds A and C 10 m off (seen, beyond a say), not B unseen at 20 m", way("c0") == far["name"] and a in ear("c0") and cc in ear("c0") and b not in ear("c0"), f"way {way('c0')}; earshot {ear('c0')}")
    mx = far.get("max_chars") or 0
    c.check(s, "the box takes no more than the far way's max_chars", mx > 0 and len(ty("c1").get("words") or "") == mx, f"{len(ty('c1').get('words') or '')} of {mx}")
    c.check(s, "B 20 m off, unseen, hears the call", bool(heard(b, "Over here!")), "B's speech rows")
    L = log(out)
    c.check(s, "lines went by human_speak in their ways", f"({far['name']})" in L and f"({names[0]})" in L, "client.log say lines")
    c.check(s, "Settings › Controls offers the Way key", any(t.startswith("bind:Way:") for t in (d["k0"].get("tags") or {})), str([t for t in (d["k0"].get("tags") or {}) if t.startswith("bind:")][:20]))


def select_facing(preset, *, orbit=False):
    camera = "click:@settings:camera:orbit;wait:0.4;" if orbit else ""
    return (
        "click:@menu;wait:0.4;click:@menu:Settings;wait:0.5;"
        f"click:@settings:facing:{preset};wait:0.4;{camera}key:Escape:tap;wait:0.5;"
    )


def check_facing(c, scenario, out, preset):
    path = os.path.join(out, "settings.json")
    selected = json.load(open(path)).get("facing") if os.path.exists(path) else None
    c.check(scenario, f"Settings saved {preset} facing", selected == preset, repr(selected))


@scenario("reversal")
def reversal(run, c):
    """Reversing a remote player's travel keeps its look-4 gait under both local facing presets."""
    for preset in ("natural", "cursor"):
        reversal_one(run, c, preset)


def reversal_one(run, c, preset):
    """look-4 in the client: when another's walk reverses with their look held aside, their drawn
    legs decide walking backwards from where the authority's facing settles, not from the facing
    still coming round (for about 0.3 s it can stand 75°-180° off the new travel), so no brief
    backwards gait starts. verify.py's player identity walks east with its look held north, then
    the walk reverses to the west; my client logs their feet (`LIVING_GAME_FEET_ID`): no frame drawn
    backwards (`reverse`) in the second after the reversal, while the authority's settled offset is
    within `look_walk_deg` (so backwards would be wrong)."""
    s = f"reversal:{preset}"
    def body():
        r = subprocess.run([sys.executable, V, "sql", "--run", run, "SELECT * FROM my_body", "--as-player"], capture_output=True, text=True)
        rows = json.loads(r.stdout[r.stdout.find("["):]) if "[" in r.stdout else []
        return (rows[0]["id"] if rows else None), r.stdout + r.stderr
    other, t = body()
    if other is None:
        subprocess.run([sys.executable, V, "player", "--run", run, "join", "Turner"], capture_output=True, text=True)
        other, t = body()
    c.check(s, "a second player to walk beside me", other is not None, t[-200:])
    if other is None:
        return
    snap = f"sql|SELECT id, x, y, heading, turn, turn_s, t_ms, next_ms, vx, vy, speed, face_off, face_turn, face_turn_s FROM body WHERE id = {other}"
    plan = ("ready;click:@tip:ok;wait:0.5;" + select_facing(preset) + "sync:noon;sync:spot;wait:4;frame:0;view:30:9;wait:1;sync:other;wait:2;sync:go;wait:3;sync:walking;"
            "sync:rev;wait:0.3;sync:turning;wait:1.5;sync:settled;shot:01_reversed;wait:1;sync:halt;wait:1.5;quit")
    syncs = ["noon=sql|UPDATE world SET epoch_ms = {epoch_at:12} WHERE id = 0", f"spot=place_at|{{me}}|{LOOK_WALK_SPOT[0]}|{LOOK_WALK_SPOT[1]}", f"other=place_at|{other}|(mx-4)|(my+3)",
             "go=player|human_move|1|0|false;player|human_face|0|-1", f"walking={snap}", "rev=player|human_move|-1|0|false", f"turning={snap}", f"settled={snap}",
             "halt=player|human_move|0|0|false;player|human_face|0|0"]
    name = f"reversal-{preset}"
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
    check_facing(c, s, out, preset)
    scene = json.load(open(os.path.join(out, "scene.json"))) if os.path.exists(os.path.join(out, "scene.json")) else {}
    snapped = lambda k: (((scene.get("snaps") or {}).get(k) or [{}])[0])
    st = snapped("settled")
    row = (st.get("rows") or [None])[0]
    settled = None
    if row:
        settled = wrapd(math.degrees(facing_at(row, st["wall_ms"]) - heading_at(row, st["wall_ms"])))
    c.check(s, "the authority: the walk reversed west, the facing settled within look_walk_deg of it", row is not None and abs(wrapd(math.degrees(heading_at(row, st["wall_ms"])) - 180.0)) < 5 and settled is not None and abs(settled) <= 80.0, f"settled offset {settled}")
    lines = [x for x in feet_log(out) if x.get("id") == other and x.get("heading") is not None]
    t_rev = next((x["t"] for x in lines if abs(wrapd(x["heading"] - 180.0)) < 30), None)
    after = [x for x in lines if t_rev is not None and t_rev - 0.3 <= x["t"] <= t_rev + 1.0]
    back = [round(x["t"] - t_rev, 2) for x in after if x.get("reverse")]
    c.check(s, "my client logged their body through the reversal", len(after) > 20, f"{len(after)} frames")
    c.check(s, "drawn: no brief backwards gait at the reversal", not back, f"backwards at {back[:10]} s")
    json.dump({"other": other, "settled_offset_deg": settled, "frames": len(after), "backwards_at_s": back}, open(os.path.join(out, "reversal.json"), "w"), indent=1)


@scenario("talk")
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
    notes_clear(c, s, out)
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


@scenario("items")
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
    notes_clear(c, s, out)
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



@scenario("themes")
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


@scenario("film")
def film(run, c):
    """The film (`post::Film`, Settings › Play › Film): a fresh settings file starts in Soft and
    saves no choice; Settings sets Full and None and the file keeps the last; the next start reads
    it back. Stills of the three modes from one place (`01_soft`, `03_screen`, `04_off`), the
    unseen ground's edge in view, for the eye. `LIVING_GAME_FILM` must not be set."""
    s = "film"
    if os.environ.get("LIVING_GAME_FILM"):
        c.check(s, "LIVING_GAME_FILM is unset (it overrides the settings file)", False, os.environ["LIVING_GAME_FILM"])
        return
    # drive() keeps a themed run's evidence apart (`film-<theme>`): its settings file is there.
    out0 = os.path.join(ROOT, ".local/living/verify", run, "ui", f"film-{THEME}" if THEME else "film")
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


@scenario("light")
def light(run, c):
    """The light (`style::Look`, Settings › Play › Light) and the character rim (`style::CharRim`,
    Settings › Play › Character rim): a fresh settings file starts Classic with the rim Subtle and
    saves neither; Settings sets Look-dev and Strong and the file keeps them; the next start reads
    them back. Then the live script's `light:` and `rim:` switch them in one view: Look-dev
    changes the picture, Classic between two Look-devs returns to it (no more change than between
    two Classic shots), and the rim changes people only. Stills `01_classic` … `05_rim_off` for the
    eye. `LIVING_GAME_LOOK` and `LIVING_GAME_CHAR_RIM` must not be set."""
    s = "light"
    for k in ("LIVING_GAME_LOOK", "LIVING_GAME_CHAR_RIM"):
        if os.environ.get(k):
            c.check(s, f"{k} is unset (it overrides the settings file)", False, os.environ[k])
            return
    out0 = os.path.join(ROOT, ".local/living/verify", run, "ui", f"light-{THEME}" if THEME else "light")
    st = os.path.join(out0, "settings.json")
    if os.path.exists(st):
        os.remove(st)
    open_settings = "click:@menu;wait:0.4;click:@menu:Settings;wait:0.6;"
    plan = ("ready;wait:2;dump:01;" + open_settings + "click:@settings:light:lookdev;wait:0.4;dump:02;shot:02_settings;"
            "click:@settings:char_rim:strong;wait:0.4;dump:03;key:Escape:tap;wait:0.4;quit")
    out, code, text = drive(run, s, plan)
    c.check(s, "client ran and joined", code == 0, text[-300:])
    x = lambda o, k: ((dump(o, k) or {}).get("extra") or {})
    first = x(out, "01")
    c.check(s, "a fresh settings file starts Classic, rim Subtle, and saves no choice", (first.get("light"), first.get("char_rim"), first.get("light_saved"), first.get("char_rim_saved")) == ("classic", "subtle", None, None), str((first.get("light"), first.get("char_rim"), first.get("light_saved"), first.get("char_rim_saved"))))
    c.check(s, "Settings › Play › Light sets Look-dev, Character rim sets Strong", x(out, "02").get("light") == "lookdev" and x(out, "03").get("char_rim") == "strong", str((x(out, "02").get("light"), x(out, "03").get("char_rim"))))
    c.check(s, "the log names each choice", log(out).count("settings: light: ") == 1 and log(out).count("settings: character rim: ") == 1)
    saved = json.load(open(st)) if os.path.exists(st) else {}
    c.check(s, "the settings file keeps both", (saved.get("light"), saved.get("char_rim")) == ("lookdev", "strong"), str((saved.get("light"), saved.get("char_rim"))))
    seq = [("classic", "subtle"), ("lookdev", "subtle"), ("classic", "subtle"), ("lookdev", "strong"), ("lookdev", "off")]
    names = ["01_classic", "02_lookdev", "03_classic", "04_rim_strong", "05_rim_off"]
    shots = "".join(f"light:{l};rim:{r};wait:0.8;shot:{n};" for (l, r), n in zip(seq, names))
    out2, code2, _ = drive(run, s, "ready;wait:2;dump:00;wait:2;" + shots + "dump:06;quit")
    c.check(s, "the next start reads them back", (x(out2, "00").get("light"), x(out2, "00").get("char_rim")) == ("lookdev", "strong"), str((x(out2, "00").get("light"), x(out2, "00").get("char_rim"))))
    try:
        import numpy as np
        from PIL import Image
    except ImportError:
        c.check(s, "pixels: numpy and Pillow are available (uv run --with pillow --with numpy)", False)
        return
    shot = {n: np.asarray(Image.open(os.path.join(out2, f"{n}.png")).convert("RGB")).astype(int) for n in names}
    h, w = shot[names[0]].shape[:2]
    near = np.zeros((h, w), bool)
    yy, xx = np.mgrid[0:h, 0:w]
    for b in (dump(out2, "06") or {}).get("seen") or []:
        (hx, hy), (fx, fy) = b["head"], b["feet"]
        tall = max(abs(fy - hy), 8.0)
        near |= (np.abs(xx - (hx + fx) / 2) <= 0.4 * tall) & (yy >= min(hy, fy) - 0.15 * tall) & (yy <= max(hy, fy) + 0.1 * tall)
    changed = lambda p, q: (np.abs(shot[p] - shot[q]).max(2) > 6).mean() * 100
    base = changed("01_classic", "03_classic")
    c.check(s, "Look-dev changes the picture", changed("01_classic", "02_lookdev") > base + 5, f"{changed('01_classic', '02_lookdev'):.2f}% against {base:.2f}% between the Classics")
    # People idle and the sun moves meanwhile: Classic after Look-dev is Classic again.
    c.check(s, "Classic after Look-dev changes no more than idle motion", base <= 5.0, f"{base:.2f}%")
    rim = np.abs(shot["04_rim_strong"] - shot["05_rim_off"]).max(2) > 6
    c.check(s, "the rim changes people, little else", (rim & near).sum() > 40 and (rim & ~near).mean() * 100 <= base * 1.25 + 0.5, f"{int((rim & near).sum())} px on people, {(rim & ~near).mean() * 100:.2f}% elsewhere")


@scenario("hair")
def hair(run, c):
    """The hair shine (`style::HAIR_SHINES`, Settings › Play › Hair shine): a fresh settings file
    starts on Crown and saves no choice; Settings sets Soft and Today and the file keeps the last;
    the next start reads it back. Then, with a resident's window open and the camera framing them
    as they speak to me (admin `mind_say`, as in `talk`), the live script's `shine:` switches it in
    one view close up, each shine between two shots of Crown: the hair changes, and away from every
    head no more changes than between those two Crowns (the sun and people move meanwhile).
    `LIVING_GAME_HAIR_SHINE` and `LIVING_GAME_HAIR_RING` must not be set."""
    s = "hair"
    for k in ("LIVING_GAME_HAIR_SHINE", "LIVING_GAME_HAIR_RING"):
        if os.environ.get(k):
            c.check(s, f"{k} is unset (it overrides the settings file)", False, os.environ[k])
            return
    out0 = os.path.join(ROOT, ".local/living/verify", run, "ui", "hair")
    st = os.path.join(out0, "settings.json")
    if os.path.exists(st):
        os.remove(st)
    open_settings = "click:@menu;wait:0.4;click:@menu:Settings;wait:0.6;"
    plan = ("ready;wait:2;dump:01;" + open_settings + "click:@settings:hair:soft;wait:0.4;dump:02;shot:02_settings;"
            "click:@settings:hair:today;wait:0.4;dump:03;key:Escape:tap;wait:0.4;quit")
    out, code, text = drive(run, s, plan)
    c.check(s, "client ran and joined", code == 0, text[-300:])
    x = lambda o, k: ((dump(o, k) or {}).get("extra") or {})
    c.check(s, "a fresh settings file starts on Crown and saves no choice", x(out, "01").get("hair_shine") == "crown" and x(out, "01").get("hair_shine_saved") is None, str((x(out, "01").get("hair_shine"), x(out, "01").get("hair_shine_saved"))))
    c.check(s, "Settings › Play › Hair shine sets Soft, then Today", x(out, "02").get("hair_shine") == "soft" and x(out, "03").get("hair_shine") == "today", str((x(out, "02").get("hair_shine"), x(out, "03").get("hair_shine"))))
    c.check(s, "the log names each choice", log(out).count("settings: hair shine: ") == 2)
    saved = json.load(open(st)).get("hair_shine") if os.path.exists(st) else None
    c.check(s, "the settings file keeps the last choice", saved == "today", str(saved))
    # The same settings file: the next start reads Today back. Then A, placed beside me and held
    # still, speaks to me with their window open. Zoom the top-down camera to Near,
    # then capture the shines in turn.
    a, _ = residents(run)
    thought = json.dumps({"kind": "talk", "summary": "", "detail": "", "latency_ms": 0, "tokens": 0, "model": "verify-ui scene", "reference": ""})
    answer = f'answer=mind_say|{a}|"Good day to you."|{{me}}|""|0|{thought}'
    seq = ["crown", "today", "crown", "soft", "crown"]
    shots = "".join(f"shine:{v};wait:0.7;shot:{i + 1:02d}_{v};" for i, v in enumerate(seq))
    plan = (f"ready;wait:2;dump:00;shine:crown;sync:scene;wait:1.5;menu:f@id:{a};wait:0.5;click:@acts:0:window;wait:1;sync:answer;wait:0.5;cursor:0.70,0.55;notches:30;wait:4;" + shots + "dump:06;quit")
    out2, code2, _ = drive(run, s, plan, places=[f"{a}:-1.5:1.5"], syncs=[answer])
    c.check(s, "the next start reads it back", x(out2, "00").get("hair_shine") == "today", str(x(out2, "00").get("hair_shine")))
    c.check(s, "A's window is open in the photographs", any(w.startswith("Person") for w, _ in wins(dump(out2, "06"))), str(wins(dump(out2, "06"))))
    try:
        import numpy as np
        from PIL import Image
    except ImportError:
        c.check(s, "pixels: numpy and Pillow are available (uv run --with pillow --with numpy)", False)
        return
    names = [f"{i + 1:02d}_{v}" for i, v in enumerate(seq)]
    shot = {n: np.asarray(Image.open(os.path.join(out2, f"{n}.png")).convert("RGB")).astype(int) for n in names}
    h, w = shot[names[0]].shape[:2]
    near = np.zeros((h, w), bool)
    yy, xx = np.mgrid[0:h, 0:w]
    for b in (dump(out2, "06") or {}).get("seen") or []:
        (hx, hy), (fx, fy) = b["head"], b["feet"]
        tall = max(abs(fy - hy), 8.0)
        near |= ((xx - hx) / (0.32 * tall)) ** 2 + ((yy - hy - 0.06 * tall) / (0.22 * tall)) ** 2 <= 1.0
    changed = lambda p, q: np.abs(shot[p] - shot[q]).max(2) > 10
    for k in (1, 3):
        before, this, after = names[k - 1], names[k], names[k + 1]
        d, base = changed(before, this), changed(before, after)
        c.check(s, f"{seq[k].title()} differs from Crown on the hair", (d & near).sum() > 40, f"{int((d & near).sum())} px near heads")
        far, far0 = (d & ~near).mean() * 100, (base & ~near).mean() * 100
        # People's idle motion, the speech bubble's timer and the sun's shadows move meanwhile:
        # within a quarter of the Crowns' own change.
        c.check(s, f"away from every head, {seq[k].title()} changes no more than the Crowns before and after it", far <= far0 * 1.25 + 0.05, f"{far:.3f}% against {far0:.3f}%")


def act(actor, a):
    """An admin `mind_act` for a resident, as its mind would decide (scene setup)."""
    inner = json.dumps(a, separators=(",", ":")).replace('"{me}"', "{me}")  # the player's id, filled in by drive.py
    return "mind_act|%d|%s|\"verify-ui\"" % (actor, json.dumps([inner]))


@scenario("offers")
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
    notes_clear(c, s, out)
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
# and what holds it up there: a kit fixture's file or directory; whether it is tall enough to
# be an occluder, so the camera's fade (`envs::cutaway`) considers it at all; and whether it is what
# I walk on there (a flight, a terrace, the quay: never faded), or only beside me (a retaining wall
# below the edge I stand on, which may fade when it stands between the camera and me).
SUPPORTS = [
    ("stairs", 458.0, 755.0, "envs/cullet/stairs/stairs_ladder_wynd_strand_to_low.glb", True, True),
    ("terrace", 584.0, 720.8, "envs/cullet/marver_terrace/marver_terrace.glb", False, True),
    ("quay", 450.0, 782.6, "envs/cullet/quay/", False, True),
    # At the upper level's edge above a retaining wall: the drop's tiles keep you 1-1.5 m from
    # it, so it is beside you, never under you; it may fade when it stands between the camera
    # and you, as anything that hides you does.
    ("wall", 440.0, 751.6, "envs/cullet/retaining_wall/wall_002.glb", False, False),
]
# Where the player stands first, away from every spot: the cutaway names what holds me up once,
# as I come onto it, and the character keeps its place between drives.
AWAY = (540.5, 766.5)


@scenario("support", cullet=True)
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
    parts = re.split(r"live script: sync:([^\n]+?)(?= \(me )", L)
    seg = {parts[i]: parts[i + 1] for i in range(1, len(parts) - 1, 2)}
    for name, x, y, part, occluder, walked in SUPPORTS:
        t = seg.get(name, "")
        held = set(re.findall(r"cutaway: (\S+) holds me up", t))
        faded = re.findall(r"cutaway: (\S+) fades to", t)
        def supports(file):
            return os.path.dirname(file) == part.rstrip("/") if part.endswith("/") else file == part

        mine = [f for f in held if supports(f)]
        if occluder:
            c.check(s, f"{name}: the cutaway finds what holds me up ({part})", bool(mine), f"held {sorted(held)}")
            # Only the plan's own flight is there: no other kit file of its kind drawn on it
            # (stairs-place: a Store Wynd flight stood at the Ladder Wynd's foot).
            folder = os.path.dirname(part)
            others = sorted(f for f in held if os.path.dirname(f) == folder and f != part)
            c.check(s, f"{name}: no other {os.path.basename(folder)} model stands there", not others, f"also held {others}")
        # What held me up there, and what I walk on there, never fades there.
        bad = [f for f in faded if f in held or (walked and supports(f))]
        c.check(s, f"{name}: nothing under or beside my feet fades", t != "" and not bad, f"faded {bad}" if t else "no log for this spot")
    c.check(s, "photographs of each spot", all(os.path.exists(os.path.join(out, f"{n}.png")) for n, *_ in SUPPORTS))


@scenario("pick")
def pick(run, c):
    """Two people overlapping on screen: the cursor on the one in front (its chest, with the one
    behind standing where the cursor's ground point falls) names, hovers and addresses that one.
    The pick is one function for the nameplate, Enter and combat's target (living/game/src/pick.rs);
    before it, Enter took the hovered person nearest the cursor's ground point: the one behind."""
    s = "pick" + BEARING_SUFFIX
    a, b = residents(run)
    line = f"You in front, {int(time.time()) % 100000}."  # its own line: said rows from earlier drives don't count
    # A stands screen-left; B is farther along the view, where A's chest ray meets the ground.
    plan = ("ready;frame:0;yaw:{BEARING};wait:1.5;sync:scene;wait:2;point:{A}:1.3;wait:0.8;shot:01_pointed;dump:01;"
            "key:Enter:tap;wait:0.6;shot:02_to_them;dump:02;type:{LINE};enter;wait:1.2;dump:03;key:Escape:tap;wait:0.6;"
            "point:{A}:1.3;wait:0.8;tap;wait:0.8;dump:04;key:Escape:tap;wait:0.4;"
            "sync:stack;wait:1;point:{A}:1.0;wait:0.5;dump:05a;wait:0.5;dump:05b;wait:0.5;dump:05c;shot:05_stacked;quit").replace("{A}", str(a)).replace("{LINE}", line).replace("{BEARING}", str(BEARING))
    # Last, both on one spot (stacked exactly on screen): one answer every frame, the nearer the camera.
    ax, ay = bearing_offset(-3.0, -1.0)
    bx, by = bearing_offset(-3.0, -2.5)
    stack = f"stack=place_at|{a}|(mx{ax:+.4f})|(my{ay:+.4f});place_at|{b}|(mx{ax:+.4f})|(my{ay:+.4f})"
    out, code, text = drive(run, s, plan, places=[f"{a}:{ax:.4f}:{ay:.4f}", f"{b}:{bx:.4f}:{by:.4f}"], syncs=[stack])
    c.check(s, "client ran and joined", code == 0, text[-300:])
    d = {k: dump(out, k) for k in ["01", "02", "03", "04"]}
    L = log(out)
    c.check(s, "requested bearing is shown", at_bearing(d["01"]), repr(view(d["01"])))
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


@scenario("bar")
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
    notes_clear(c, s, out)
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
    # The shipped script: health, stamina and focus ("Mana") shown, always (meters-always);
    # energy and hunger feed the statuses off the screen.
    names = [m["name"] for m in ms]
    c.check(s, "the bars are the world's shown meters (health, stamina, mana; always), each within its max", names[:3] == ["health", "stamina", "focus"] and not ({"energy", "hunger"} & set(names)) and all(0 <= m["value"] <= m["max"] + 1e-3 and m["label"] for m in ms), str(ms))
    c.check(s, "the pills are the rules' statuses, none plain", all(x["tone"] != "Plain" for x in me.get("statuses") or []), str(me.get("statuses")))


def cursor(d):
    c = ((d or {}).get("extra") or {}).get("cursor")
    return (c["x"], c["y"]) if c else None


def view(d):
    return ((d or {}).get("extra") or {}).get("view") or {}


def ground(d):
    return ((d or {}).get("extra") or {}).get("cursor_ground")


def select_camera_preset(preset):
    return (
        "click:@menu;wait:0.4;click:@menu:Settings;wait:0.5;click:@settings:page:camera;wait:0.4;"
        f"click:@settings:camera_preset:{preset};wait:0.4;key:Escape:tap;wait:0.5;"
    )


@scenario("camera", explicit=True)
def camera(run, c):
    """Drive real line-wheel messages at the three top-down knots, with the field off and on."""
    s = "camera" + BEARING_SUFFIX
    ids = residents(run, 3)
    if len(ids) != 3:
        c.check(s, "three residents available", False, repr(ids))
        return
    front, back, behind_wall = ids
    # Land seed 7, Brackenford. The wood line heads north from grass into Forest tiles.
    # The roof point is on walking ground under the north eave of the market stall.
    street, wood, behind_trees = (420.5, 255.5), (276.5, 395.5), (277.5, 389.5)
    roof = (411.5, 256.5) if BEARING == 135 else (412.5, 256.5)
    syncs = [
        "noon=sql|UPDATE world SET epoch_ms = {epoch_at:12} WHERE id = 0",
        'fov_off=set_world_law|"fov_on"|"false"',
        'fov_on=set_world_law|"fov_on"|"true"',
        f"street=place_at|{{me}}|{street[0]}|{street[1]}",
        f"wood=place_at|{{me}}|{wood[0]}|{wood[1]};place_at|{front}|{behind_trees[0]}|{behind_trees[1]}",
    ]
    knots = (("far", -30, 0.0, 19.0, 65.0, 46.0),
             ("middle", 11, 0.55, 12.0, 58.0, 44.0),
             ("near", 30, 1.0, 8.0, 48.0, 42.0))
    for field in ("off", "on"):
        plan = "ready;" + select_camera_preset("ours") + f"yaw:{BEARING};sync:noon;sync:fov_{field};sync:street;wait:3;sync:scene;look:0;wait:2;cursor:0.70,0.55;wait:0.5;dump:initial;pan:300;drag:250;wait:0.5;dump:fixed;"
        for stop, wheel, *_ in knots:
            plan += f"notches:{wheel};wait:1.5;dump:{stop};shot:{stop};"
            plan += f"point:{front}:0;wait:0.6;dump:{stop}_ground;point:{front}:0.8;wait:0.6;dump:{stop}_hover;"
            if stop == "far":
                plan += "key:KeyF:down;wait:0.5;notches:3;wait:0.5;dump:held_wheel;key:Escape:tap;key:KeyF:up;wait:0.5;"
            plan += f"tap;wait:0.7;dump:{stop}_selected;shot:{stop}_window;"
            if stop == "middle":
                plan += f"cursor:@win:Person{front}:head;wait:0.5;notches:2;wait:0.5;dump:window_wheel;"
            plan += f"chat:close;wait:0.3;click:@win:Person{front}:close;wait:0.5;cursor:0.70,0.55;wait:0.5;"
        plan += "sync:wood;wait:3;look:180;wait:1;look:0;wait:1.5;"
        for stop, wheel, *_ in knots:
            plan += f"notches:{wheel};wait:1.5;dump:wood_{stop};shot:wood_{stop};"
        roof_syncs = []
        for stop, wheel, *_ in knots:
            plan += f"sync:clear_{stop};wait:3;notches:{wheel};wait:1.5;"
            plan += f"sync:roof_{stop};wait:3;look:180;wait:0.6;look:0;wait:1.2;dump:roof_{stop};shot:roof_{stop};"
            roof_syncs += [
                f"clear_{stop}=place_at|{{me}}|{street[0]}|{street[1]}",
                f"roof_{stop}=place_at|{{me}}|{roof[0]}|{roof[1]}",
            ]
        # The scene turns `fov_on` and the clock; the fixture puts the world's own law and daylight back.
        with sight_fixture(run, {"fov_on": "false"}), resident_fixture(run, ids):
            out, code, text = drive(run, f"{s}-{field}", plan + "quit",
                                    places=[f"{front}:0:-2.5", f"{back}:2.5:4.5", f"{behind_wall}:1.0:-14.0"], syncs=syncs + roof_syncs,
                                    env={"LIVING_GAME_DEV": "1", "RUST_LOG": "info,wgpu=warn,naga=warn,living_game::envs=debug"})
        c.check(s, f"field {field}: client joined and finished", code == 0, text[-300:])
        initial = view(dump(out, "initial"))
        c.check(s, f"field {field}: fresh settings start at middle zoom", abs(initial.get("zoom", -1.0) - 0.55) < 0.001, repr(initial))
        fixed = view(dump(out, "fixed"))
        c.check(s, f"field {field}: left drag and pan keep the chosen bearing", at_bearing(dump(out, "fixed")), repr(fixed))
        held = dump(out, "held_wheel") or {}
        c.check(s, f"field {field}: the held action wheel consumes line-wheel input",
                abs(view(held).get("zoom", -1.0)) < 0.001 and bool((held.get("wheel") or {}).get("held")), repr(held.get("wheel")))
        scene = dump(out, "scene") or {}
        row = (scene.get("placed") or {}).get(str(front))
        after_window = view(dump(out, "window_wheel"))
        c.check(s, f"field {field}: wheel over a person window keeps zoom at middle", abs(after_window.get("zoom", -1.0) - 0.55) < 0.001, repr(after_window))
        ranges = []
        perceived = []
        visible = []
        trace = log(out)
        for stop, _, z, height, pitch, fov in knots:
            d = dump(out, stop) or {}
            v = view(d)
            data = d.get("extra") or {}
            sense = data.get("facing_sight") or {}
            ranges.append(sense.get("sight"))
            perceived.append(set(d.get("perceived") or []))
            visible.append({a["id"] for a in d.get("seen") or []})
            good = all(abs(v.get(k, -100.0) - expected) < tolerance
                       for k, expected, tolerance in (("zoom", z, 0.001), ("height", height, 0.1),
                                                       ("pitch", pitch, 0.1), ("fov", fov, 0.1))) and at_bearing(d)
            c.check(s, f"{field} {stop}: camera reaches the curve knot at the requested bearing", good and v.get("mode") == "top-down", repr(v))
            c.check(s, f"{field} {stop}: authority sight and Shade active",
                    sense.get("on") == (field == "on") and sense.get("source") == "Authority" and data.get("sight_look") == "shade", repr(sense))
            point = ground(dump(out, f"{stop}_ground"))
            c.check(s, f"{field} {stop}: ground ray reaches the resident's known tile",
                    point and row and math.hypot(point[0] - row[0], point[2] - row[1]) < 0.15, repr((point, row)))
            hover = dump(out, f"{stop}_hover") or {}
            selected = dump(out, f"{stop}_selected") or {}
            c.check(s, f"{field} {stop}: point and tap select the resident",
                    hover.get("under") == front and (selected.get("typing") or {}).get("to") == front,
                    repr((hover.get("under"), selected.get("typing"))))
            if stop == "middle":
                label = next((a["label"] for a in selected.get("hovered", []) if a["id"] == front), "")
                top = next((name for kind, name in selected.get("naming", []) if kind == "target"), "")
                c.check(s, f"{field}: middle hover is short and the top plate keeps the full description",
                        bool(label) and len(top) > len(label), repr((label, top)))
            c.check(s, f"{field} {stop}: street, woods and roof stills captured",
                    all(os.path.isfile(os.path.join(out, f"{prefix}{stop}.png")) for prefix in ("", "wood_", "roof_")))
            wood_dump = dump(out, f"wood_{stop}") or {}
            c.check(s, f"{field} {stop}: resident in generic forest remains in the scoped view",
                    front in (wood_dump.get("perceived") or []), repr(wood_dump.get("perceived")))
            under_roof = partition_sync(trace, f"roof_{stop}")[2].partition(f"live script: dump:roof_{stop}")[0]
            c.check(s, f"{field} {stop}: the market stall roof enters cutaway",
                    cutaway_fades(under_roof, "market_stall"), under_roof[-350:])
        c.check(s, f"{field}: zoom keeps the authority's sight radius", ranges[0] is not None and len(set(ranges)) == 1, repr(ranges))
        c.check(s, f"{field}: the resident behind the wall stays outside the scoped view",
                all(behind_wall not in rows for rows in visible + perceived), repr((visible, perceived)))
        if field == "on":
            c.check(s, "field on: resident behind the player stays out of every pick list", all(back not in rows for rows in visible + perceived), repr((visible, perceived)))
        else:
            c.check(s, "field off: the rear resident is perceived", all(back in rows for rows in perceived), repr(perceived))


@scenario("camera-rotate", explicit=True)
def camera_rotate(run, c):
    """Turn at Middle, drive real W, aim/pick, cut away an awning and snap north."""
    s = "camera-rotate"
    resident = residents(run, 1)[0]
    open_settings = "click:@menu;wait:0.4;click:@menu:Settings;wait:0.6;"
    drag = "mouse:middle:down;motion:3,0;wait:0.15;dump:threshold;motion:447,0;mouse:middle:up;"
    plan = ("ready;click:@tip:ok;wait:0.3;sync:noon;sync:street;wait:3;sync:scene;cursor:0.55,0.42;wait:0.3;"
            "dump:north;shot:middle-north;" + drag + "wait:0.6;dump:turned;shot:middle-135;"
            f"point:{resident}:0.9;wait:0.4;dump:resident;point:{resident}:0;wait:0.4;dump:ground;"
            "cursor:;key:KeyW:down;wait:0.8;key:KeyW:up;wait:0.6;dump:walked;"
            "sync:roof;wait:3;dump:awning;shot:awning;key:KeyN:tap;wait:0.3;dump:key-snap;"
            "cursor:0.60,0.40;rotate:135;wait:0.3;dump:gesture;"
            "mouse:middle:down;motion:2,1;mouse:middle:up;wait:0.3;dump:tap-snap;"
            + open_settings + "click:@settings:page:rotation;wait:0.4;shot:rotation-settings;click:@settings:camera_rotate_speed:2;wait:0.4;"
            "click:@settings:camera_rotate_invert;wait:0.4;click:@settings:page:controls;wait:0.4;"
            "click:@bind:NorthUp:0;wait:0.4;key:KeyY:tap;wait:0.4;"
            "click:@settings:page:play;wait:0.4;key:Escape:tap;cursor:0.60,0.40;wait:0.6;"
            "rotate:30;wait:0.3;dump:fast-invert;"
            + open_settings + "click:@settings:page:camera;wait:0.4;click:@settings:camera_copy;wait:0.4;"
            "key:Escape:tap;cursor:0.60,0.40;wait:0.4;key:KeyY:tap;wait:0.3;dump:rebound-snap;"
            + open_settings + "click:@settings:page:rotation;wait:0.4;click:@settings:camera_rotate;wait:0.4;"
            "key:Escape:tap;cursor:0.60,0.40;wait:0.6;rotate:90;wait:0.3;dump:disabled;quit")
    out, code, msg = drive(run, s, plan, places=[f"{resident}:2:-2"], syncs=[
        "noon=sql|UPDATE world SET epoch_ms = {epoch_at:12} WHERE id = 0",
        'street=set_world_law|"fov_on"|"false";place_at|{me}|420.5|255.5',
        "roof=place_at|{me}|411.5|256.5",
    ], env={"LIVING_GAME_DEV": "1", "RUST_LOG": "info,wgpu=warn,naga=warn,living_game::envs=debug"})
    c.check(s, "client joined and finished", code == 0, msg[-300:])
    for label, yaw in (("north", 0), ("threshold", 0), ("turned", 135), ("awning", 135),
                       ("key-snap", 0), ("gesture", 135), ("tap-snap", 0), ("fast-invert", 300), ("rebound-snap", 0), ("disabled", 0)):
        d = dump(out, label)
        c.check(s, f"{label}: bearing {yaw}° at Middle", at_bearing(d, yaw) and abs(view(d).get("zoom", -1) - 0.55) < 0.001, repr(view(d)))
    picked = (dump(out, "resident") or {}).get("under")
    c.check(s, "the rotated camera picks the resident", picked == resident, repr(picked))
    row = ((dump(out, "scene") or {}).get("placed") or {}).get(str(resident))
    hit = ground(dump(out, "ground"))
    c.check(s, "the rotated camera ray reaches the resident's ground point",
            bool(row and hit and math.hypot(row[0] - hit[0], row[1] - hit[2]) < 0.15), repr((row, hit)))
    before, after = [(dump(out, name) or {}).get("me_at", {}).get("body") for name in ("turned", "walked")]
    if before and after:
        dx, dy = [after[k] - before[k] for k in ("x", "y")]
        up, right = (dx + dy) / math.sqrt(2), (-dx + dy) / math.sqrt(2)
        c.check(s, "W moves up-screen at 135°", up > 0.5 and abs(right) < up * 0.25, repr((dx, dy, up, right)))
    else:
        c.check(s, "W moves up-screen at 135°", False, repr((before, after)))
    trace = partition_sync(log(out), "roof")[2].partition("live script: dump:awning")[0]
    c.check(s, "the market awning cuts away at 135°", cutaway_fades(trace, "market_stall"), trace[-500:])
    c.check(s, "both Middle stills captured", all(os.path.isfile(os.path.join(out, f"middle-{name}.png")) for name in ("north", "135")))
    prefs = dump(out, "settings") or {}
    c.check(s, "the rotation settings are saved", prefs.get("camera_rotate") is False
            and prefs.get("camera_rotate_speed") == 2 and prefs.get("camera_rotate_invert") is True)
    c.check(s, "the new north key is saved", (prefs.get("binds") or {}).get("NorthUp") == ["KeyY"])
    copied = dump(out, "camera-tuning") or {}
    c.check(s, "Copy values exports the live bearing", abs(copied.get("bearing", -1) - 300) < 0.05, repr(copied))


@scenario("camera-tuning", explicit=True)
def camera_tuning(run, c):
    """Change live camera values and export them through the real Settings panel."""
    s = "camera-tuning"
    plan = (
        "ready;click:@tip:ok;wait:0.5;click:@menu;wait:0.4;click:@menu:Settings;wait:0.5;"
        "click:@settings:camera:top-down;wait:0.4;click:@settings:page:camera;wait:0.5;"
        "click:@settings:camera_preset:ours;wait:0.5;dump:before;"
        "click:@settings:camera_slider:height:middle;wait:0.5;dump:live;"
        "click:@settings:camera_pitch:fixed;wait:0.5;"
        "dump:fixed;key:Escape:tap;wait:0.5;cursor:0.72,0.62;notches:30;wait:1.5;dump:near;shot:near;"
        "notches:-9;wait:1.5;click:@menu;wait:0.4;click:@menu:Settings;wait:0.5;"
        "click:@settings:page:camera;wait:0.4;click:@settings:camera_pitch:late;wait:0.4;"
        "click:@settings:camera_slider:tilt_start;wait:0.4;click:@settings:camera_slider:near_pitch;wait:0.4;"
        "click:@settings:camera_copy;wait:0.5;dump:late_middle;shot:panel;"
        "key:Escape:tap;wait:0.5;cursor:0.72,0.62;notches:30;wait:1.5;dump:late_near;quit"
    )
    out, code, detail = drive(run, s, plan, env={"LIVING_GAME_DEV": "1"})
    c.check(s, "client ran and joined", code == 0, detail[-300:])
    before, live, fixed, near = [view(dump(out, name)) for name in ("before", "live", "fixed", "near")]
    c.check(s, "height slider changes the live view with Settings open",
            live.get("height", 0) > before.get("height", 0) + 5, repr((before, live)))
    c.check(s, "fixed pitch and FOV stay the same while zoom changes height",
            fixed and near and abs(fixed["pitch"] - near["pitch"]) < 0.1
            and abs(fixed["fov"] - near["fov"]) < 0.1 and fixed["height"] > near["height"] + 5,
            repr((fixed, near)))
    def read(name):
        path = os.path.join(out, name)
        return json.load(open(path)) if os.path.exists(path) else {}
    exported = read("camera-tuning.json")
    bearing = exported.pop("bearing", None)
    late = exported.get("late_tilt") or {}
    middle, close = [view(dump(out, name)) for name in ("late_middle", "late_near")]
    c.check(s, "Copy values writes the persisted live tuning and the displayed bearing",
            bool(late) and exported == read("settings.json").get("camera_tuning")
            and abs(exported["fixed_pitch"] - fixed.get("pitch", 0)) < 0.1
            and abs(late["tilt_start"] - 0.5) < 0.01
            and bearing is not None and at_bearing(dump(out, "late_middle"), bearing), repr((exported, bearing)))
    c.check(s, "Tilt near eases between the base and near pitches",
            bool(late and middle and close) and late["tilt_start"] < middle["zoom"] < 0.6
            and late["near_pitch"] < middle["pitch"] < exported["fixed_pitch"]
            and abs(close["pitch"] - late["near_pitch"]) < 0.1, repr((late, middle, close)))


@scenario("camera-lol", explicit=True)
def camera_lol(run, c):
    """The closest League of Legends stop at ground, person and awning interaction distances."""
    s = "camera-lol"
    ids = residents(run, 1)
    if not ids:
        c.check(s, "resident available", False)
        return
    front = ids[0]
    name = "camera-lol"
    folder = os.path.join(ROOT, ".local/living/verify", run, "ui", f"{name}-{THEME}" if THEME else name)
    plan = (
        "ready;" + select_camera_preset("lol") +
        "sync:noon;sync:street;wait:3;sync:scene;look:0;wait:1;cursor:0.72,0.62;notches:30;wait:1.5;"
        f"dump:near;point:{front}:0;wait:0.6;dump:ground;point:{front}:0.8;wait:0.6;dump:hover;"
        f"tap;wait:0.7;dump:selected;shot:selected;chat:close;wait:0.4;click:@win:Person{front}:close;wait:0.5;"
        "sync:roof;wait:3;dump:under_awning;shot:under_awning;"
        "hold:0;wait:1.4;stop;wait:0.7;dump:after_walk;quit"
    )
    syncs = [
        "noon=sql|UPDATE world SET epoch_ms = {epoch_at:12} WHERE id = 0",
        'street=set_world_law|"fov_on"|"false";place_at|{me}|420.5|255.5',
        "roof=place_at|{me}|412.5|256.5",
    ]
    out, code, detail = drive(run, name, plan, places=[f"{front}:0:-1.7"], syncs=syncs,
        env={"LIVING_GAME_DEV": "1", "LIVING_GAME_FEET": os.path.join(folder, "feet.jsonl"),
             "RUST_LOG": "info,wgpu=warn,naga=warn,living_game::envs=debug"})
    c.check(s, "client joined and finished", code == 0, detail[-300:])
    v = view(dump(out, "near"))
    c.check(s, "the nearest LoL stop is 4.8 m at 56° and 40° FOV",
        all(abs(v.get(k, -100.0) - target) < 0.1 for k, target in (("height", 4.8), ("pitch", 56), ("fov", 40))), repr(v))
    position = ((dump(out, "scene") or {}).get("placed") or {}).get(str(front))
    hit = ground(dump(out, "ground"))
    c.check(s, "the ground ray reaches the resident's known tile",
        hit and position and math.hypot(hit[0] - position[0], hit[2] - position[1]) < 0.15, repr((hit, position)))
    selected = (dump(out, "selected") or {}).get("typing") or {}
    hover = dump(out, "hover") or {}
    c.check(s, "the point and tap pick the resident", hover.get("under") == front and selected.get("to") == front,
        repr((hover.get("under"), selected)))
    trace = log(out)
    roof = partition_sync(trace, "roof")[2].partition("live script: dump:under_awning")[0]
    c.check(s, "the market awning enters cutaway", cutaway_fades(roof, "market_stall"),
        roof[-300:])
    metrics = clearance_metrics(out, "hold:0", "dump:after_walk")
    c.check(s, "the eye clears the ground and stays continuous while walking out from the awning",
        metrics["frames"] >= 20 and metrics["min_clearance_m"] >= 0.3
        and metrics["walk_m"] > 1.0 and metrics["max_eye_height_step_m"] < 0.25, repr(metrics))


def clearance_metrics(out, first, last):
    trace = log(out)
    start = re.search(r"live script: " + re.escape(first) + r" .*?, t ([\d.]+) s\)", trace)
    end = re.search(r"live script: " + re.escape(last) + r" .*?, t ([\d.]+) s\)", trace)
    eyes = [row for row in feet_log(out) if start and end and float(start[1]) <= row["t"] <= float(end[1])
            and row.get("sim") and row.get("eye") and row.get("eye_clearance") is not None]
    if eyes:
        height = [r["eye"][1] for r in eyes]
        clearance = min(r["eye_clearance"] for r in eyes)
        jump = max((abs(b - a) for a, b in zip(height, height[1:])), default=0.0)
        walk = math.dist(eyes[0]["sim"], eyes[-1]["sim"])
        heights = [r["eye_height"] for r in eyes]
        lifts = [min(heights), max(heights)]
    else:
        clearance, jump, walk, lifts = 0.0, math.inf, 0.0, [0.0, 0.0]
    metrics = {"frames": len(eyes), "walk_m": walk, "min_clearance_m": clearance,
               "max_eye_height_step_m": jump, "eye_height_range_m": lifts}
    with open(os.path.join(out, "clearance.json"), "w") as f:
        json.dump(metrics, f, indent=2)
    return metrics


@scenario("camera-lol-ridge", explicit=True)
def camera_lol_ridge(run, c):
    """Cross a ridge where the nominal 4.8 m eye would run below the ground."""
    s = "camera-lol-ridge"
    folder = os.path.join(ROOT, ".local/living/verify", run, "ui", f"{s}-{THEME}" if THEME else s)
    # The shipped island's land_dump shows the ground under the camera rising from
    # 0.54 to 7.35 m above the player's path along this westbound stretch.
    plan = ("ready;" + select_camera_preset("lol") +
            "sync:ridge;wait:4;cursor:0.72,0.62;notches:30;wait:1.5;dump:base;hold:270;"
            "wait:1.4;stop;wait:0.6;dump:lifted;shot:ridge;quit")
    out, code, detail = drive(run, s, plan, syncs=["ridge=place_at|{me}|564.5|983.5"],
        env={"LIVING_GAME_DEV": "1", "LIVING_GAME_FEET": os.path.join(folder, "feet.jsonl")})
    c.check(s, "client joined and walked at the LoL nearest stop", code == 0, detail[-300:])
    metrics = clearance_metrics(out, "hold:270", "dump:lifted")
    base, lifted = metrics["eye_height_range_m"]
    c.check(s, "the clearance guard lifts the eye when the ridge crosses its nominal position",
        metrics["frames"] >= 20 and metrics["walk_m"] >= 3.0 and base < 4.9 and lifted > 5.2, repr(metrics))
    c.check(s, "the eye stays above terrain without a discontinuous lift",
        metrics["min_clearance_m"] >= 0.299 and metrics["max_eye_height_step_m"] < 0.25, repr(metrics))


@scenario("camera-lod", explicit=True)
def camera_lod(run, c):
    """Compare the eight-model cap with no cap on the default and the closer LoL preset."""
    camera_lod_one(run, c, "ours-fixed")
    camera_lod_one(run, c, "lol")


def camera_lod_one(run, c, preset):
    from datetime import datetime
    s = ("camera-lod" if preset == "ours-fixed" else "camera-lod-lol") + BEARING_SUFFIX
    ids = sorted(r["id"] for r in sql(run, "SELECT id, name, alive FROM character WHERE kind = 'person'")
                 if r.get("alive") and r.get("name") != "Verifier")[:17]
    if len(ids) < 12:
        c.check(s, "at least 12 residents available", False, repr(ids))
        return
    offsets = [(x, y) for y in (-4, -2, 0, 2, 4) for x in (-4, -2, 2, 4)]
    if preset == "lol":
        # Pack the same residents into the closer view, without placing anyone on the player.
        offsets = [(x, y) for y in (-2.3, -1.2, -0.1, 1.0) for x in (-1.7, -0.6, 0.6, 1.7)]
    places = [f"{id}:{x:.4f}:{y:.4f}" for id, (x, y) in zip(ids, (bearing_offset(*offset) for offset in offsets))]
    syncs = ['setup=set_world_law|"fov_on"|"false";place_at|{me}|420.5|255.5',
             "noon=sql|UPDATE world SET epoch_ms = {epoch_at:12} WHERE id = 0"]
    plan = "ready;" + select_camera_preset(preset) + f"yaw:{BEARING};sync:noon;sync:setup;wait:2;sync:scene;look:180;wait:4;cursor:0.68,0.42;wait:0.5;"
    knots = (("near", 30),) if preset == "lol" else (("far", -30), ("middle", 11), ("near", 30))
    for stop, notches in knots:
        plan += f"notches:{notches};wait:2;dump:{stop}_start;wait:8;dump:{stop}_end;shot:{stop};"
    metrics = {}
    for arm, cap in (("cap-8", "8"), ("uncapped", "0")):
        ev = os.path.join(ROOT, ".local/living/verify", run, "ui", f"{s}-{arm}")
        os.makedirs(ev, exist_ok=True)
        frames = os.path.join(ev, "frames.csv")
        out, code, msg = drive(run, f"{s}-{arm}", plan + "quit", places=places, syncs=syncs,
                               env={"LIVING_GAME_DEV": "1", "LIVING_GAME_LOD_CAP": cap, "LIVING_GAME_FRAMES": frames, "LIVING_GAME_FPS_CAP": "0"})
        c.check(s, f"{arm}: client joined and captured the zoom stops", code == 0, msg[-300:])
        frame_rows = []
        if os.path.exists(frames):
            with open(frames) as f:
                frame_rows = [tuple(map(int, line.split(","))) for line in f]
        trace = log(out)
        times = {}
        for stamp, label in re.findall(r"^([\dT:.\-]+Z).*live script: dump:(\w+)", trace, re.M):
            times[label] = int(datetime.fromisoformat(stamp).timestamp() * 1_000_000)
        scene = dump(out, "scene") or {}
        metrics[arm] = {}
        for stop, _ in knots:
            lo = times.get(f"{stop}_start", 0)
            hi = times.get(f"{stop}_end", 0)
            intervals = sorted(delta / 1000 for unix, delta, _ in frame_rows if lo < unix < hi)
            d = dump(out, f"{stop}_end") or {}
            lod = (d.get("extra") or {}).get("lod") or {}
            measured = len(intervals) >= 100 and lod.get("near", 0) + lod.get("far", 0) >= 8
            c.check(s, f"{arm} {stop}: crowded street and uncapped samples at the requested bearing", measured and at_bearing(d), repr(lod))
            if intervals:
                metrics[arm][stop] = {"frames": len(intervals), "p50_ms": intervals[len(intervals) // 2],
                                      "p99_ms": intervals[math.ceil(len(intervals) * .99) - 1], **lod}
            if arm == "cap-8":
                c.check(s, f"{stop}: eight near models at most", lod.get("near", 100) <= 8, repr(lod))
            if stop != "far":
                near = {p["id"] for p in lod.get("people", []) if not p["far"]}
                c.check(s, f"{stop}: player and at least one resident have the near model",
                        scene.get("me") in near and len(near & set(ids)) >= 1, repr(near))
    if preset == "lol":
        capped = metrics["cap-8"].get("near", {})
        uncapped = metrics["uncapped"].get("near", {})
        c.check(s, "LoL near: the crowd exceeds the cap and excess models go far",
            capped.get("far", 0) >= 1 and uncapped.get("near", 0) > 8 and capped.get("near", 9) <= 8,
            repr({arm: {k: v for k, v in rows.get("near", {}).items() if k != "people"} for arm, rows in metrics.items()}))
    evidence = os.path.join(ROOT, ".local/living/verify", run, "ui", f"{s}.json")
    with open(evidence, "w") as f:
        json.dump(metrics, f, indent=2)


@scenario("camera-faces", explicit=True)
def camera_faces(run, c):
    """Capture the ordinary middle and near framing with a generated resident beside Shino."""
    s = "camera-faces"
    generated, shino = 2, 3
    rows = look_rows(run)
    requested = {generated, shino}
    if not requested <= rows.keys() or not os.path.isfile(LOOK_BOOK):
        c.check(s, "play8 resident looks are available", False, repr(rows))
        return
    root = os.path.join(ROOT, ".local/living/verify", run, "ui")
    book = book_copy(root, json.load(open(LOOK_BOOK)), "camera-shino", drop=[rows[shino]])
    plan = ("ready;sync:noon;sync:stage;wait:3;sync:scene;look:180;wait:2;sync:face_south;wait:2;"
            "cursor:0.15,0.55;wait:0.5;dump:middle_faces;shot:middle_faces;"
            "notches:30;wait:2;dump:near_faces;shot:near_faces;quit")
    syncs = [
        "noon=sql|UPDATE world SET epoch_ms = {epoch_at:12} WHERE id = 0",
        'stage=set_world_law|"fov_on"|"false";place_at|{me}|300.5|330.5',
        "face_south=" + ";".join(f"sql|UPDATE body SET heading = 1.5707963, turn = 0.0, turn_s = 0.0, face_off = 0.0, face_turn = 0.0, face_turn_s = 0.0 WHERE id = {id}"
                                 for id in (generated, shino)),
    ]
    out, code, msg = drive(run, s, plan, places=[f"{generated}:-1:-4.0", f"{shino}:1:-4.0"],
                           syncs=syncs, extra=["--size", "3840x2160"], env={"LIVING_GAME_LOOK_BOOK": book})
    c.check(s, "client joined and captured both faces", code == 0, msg[-300:])
    for stop in ("middle", "near"):
        d = dump(out, f"{stop}_faces") or {}
        models = {m["id"]: m for m in (d.get("extra") or {}).get("lod", {}).get("people", [])}
        a, b = models.get(generated, {}), models.get(shino, {})
        c.check(s, f"{stop}: generated full model beside the Shino fallback",
                a.get("far") is False and b.get("far") is False and "Shino" in b.get("model", "")
                and os.path.isfile(os.path.join(out, f"{stop}_faces.png")), repr((a, b)))


@scenario("camera-narrow")
def camera_narrow(run, c):
    """Use the narrow viewport's own cursor projection and drive the ordinary movement keys."""
    s = "camera-narrow"
    ids = residents(run, 1)
    if not ids:
        c.check(s, "resident available", False)
        return
    person = ids[0]
    plan = (f"ready;sync:street;wait:3;sync:scene;look:0;wait:1;cursor:0.65,0.35;wait:0.5;"
            f"notches:-30;wait:1.5;point:{person}:0.8;wait:0.7;tap;wait:0.8;dump:window;shot:window;"
            f"chat:close;wait:0.4;click:@win:Person{person}:close;wait:0.4;"
            "look:;cursor:0.65,0.35;wait:2;notches:11;wait:1.5;dump:middle;"
            "key:KeyW:down;wait:0.8;key:KeyW:up;wait:0.5;"
            "key:ShiftLeft:down;key:KeyS:down;wait:0.8;key:KeyS:up;key:ShiftLeft:up;wait:0.5;dump:moved;quit")
    out, code, message = drive(run, s, plan, places=[f"{person}:0:-3"],
                               syncs=["street=place_at|{me}|420.5|255.5"], extra=["--size", "960x900"],
                               env={"RUST_LOG": "info,wgpu=warn,naga=warn,living_game::controls=debug"})
    c.check(s, "narrow client joined and finished", code == 0, message[-300:])
    d = dump(out, "window") or {}
    r = next((w["rect"] for w in d.get("windows", []) if w["win"] == f"Person{person}"), {})
    c.check(s, "the far person window stays inside the narrow viewport",
            bool(r) and r["x"] >= 0 and r["y"] >= 0 and r["x"] + r["w"] <= 960 and r["y"] + r["h"] <= 900, repr(r))
    before = (dump(out, "middle") or {}).get("me_at", {}).get("drawn")
    after = (dump(out, "moved") or {}).get("me_at", {}).get("drawn")
    c.check(s, "W then Shift+S stays on the north-south axis and runs farther south",
            before and after and abs(before[0] - after[0]) < 0.25 and after[1] > before[1] + 0.25, repr((before, after)))
    trace = log(out)
    zoom_trace = trace.partition("live script: notches:11")[2].partition("live script: dump:middle")[0]
    c.check(s, "a stationary cursor sends no look change during zoom", bool(zoom_trace) and "human_face(" not in zoom_trace, zoom_trace[-250:])


@scenario("turns")
def turns(run, c):
    """Run the Orbit pointer checks under both local facing presets."""
    for preset in ("natural", "cursor"):
        turns_one(run, c, preset)


def turns_one(run, c, preset):
    """The cursor while the view turns or zooms (Cullet walk 1, the owner: a pan turned the view
    and carried the cursor off with it). A two-finger pan, a pinch either way and a left drag,
    through the pointer's own paths (`pan:`, `pinch:`, `drag:`), with the cursor off-centre and
    nothing open: the cursor keeps its screen position (within 1 px), the view turns or zooms,
    and the ground under the cursor changes with the view."""
    s = f"turns:{preset}"
    plan = ("ready;wait:2;" + select_facing(preset, orbit=True) + "frame:0;cursor:0.72,0.62;wait:1;dump:01;shot:01_start;"
            "pan:300;wait:0.15;dump:02;shot:02_panning;wait:1.5;dump:03;shot:03_panned;"
            "pan:-500;wait:1.5;dump:04;shot:04_panned_back;"
            "pinch:0.3;wait:0.15;dump:05;wait:1.2;dump:06;shot:06_pinched_in;"
            "pinch:-0.4;wait:1.2;dump:07;shot:07_pinched_out;"
            "drag:250;wait:1.5;dump:08;shot:08_dragged;quit")
    out, code, text = drive(run, f"turns-{preset}", plan)
    c.check(s, "client ran and joined", code == 0, text[-300:])
    check_facing(c, s, out, preset)
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


LOG_LINE = re.compile(r"^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d+)Z\s+(\w+)\s+([\w:]+): (.*)$")


def timed_lines(out):
    """The client log's lines with their wall time (s since the epoch)."""
    import datetime
    rows = []
    for line in log(out).splitlines():
        m = LOG_LINE.match(line)
        if m:
            stamp = datetime.datetime.strptime(m[1][:26], "%Y-%m-%dT%H:%M:%S.%f").replace(tzinfo=datetime.timezone.utc)
            rows.append((stamp.timestamp(), m[4]))
    return rows


def first_after(lines, pattern, after, before=None):
    for t, text in lines:
        if t >= after and (before is None or t < before) and re.search(pattern, text):
            return t, text
    return None


# How long law-override waits for `cover_law` to read a cover change in force (the island's
# switch-on derivation takes about 1.9 s on a world made since cover-stall).
COVER_WAIT_S = 10.0


@scenario("law-override", explicit=True)
def law_override(run, c):
    """Value-only law edits reach a connected client in place (docs/LAW_OVERRIDE.md): each of
    the delivery, gaze and cover laws set through `set_world_law` (which writes `law_override`
    only) while a client plays, with the script revision unchanged, the client's reaction time,
    the delivery switch made before broken (no creature missing from the reads, frame by frame:
    `LIVING_GAME_SEEN_LOG`) and the world's tick gap around the call (the authority's `clock`
    sampled every ~20 ms); an ordinary law (`turn_rate`) still installs a new revision, compiled
    here with the overrides kept; a reconnect and a fresh client with overrides present take the
    set the rows choose first. The laws touched are restored afterwards.

    A cover law is in force only when the public `cover_law` row reads it: switching
    `cover_sight_on` on derives the cover ground in steps first (cover-genesis, about 1.9 s on the
    island since cover-stall), so after each cover change the driver waits (at most
    COVER_WAIT_S) for the row before it judges the client's cover effect, and records the wait
    (`in_force_s`). The world must be made at or after cover-stall (`c83ee5d1`): an older land
    has no `cover_source` and stalls the tick while it is generated again."""
    import threading
    s = "law-override"
    st = verify.load(run)
    db, token = st["db"], verify.admin_token()
    name = f"{s}-{THEME}" if THEME else s
    base = os.path.join(ROOT, ".local/living/verify", run, "ui")
    out = os.path.join(base, name)

    def q(query):
        code, body = verify.http(f"/v1/database/{db}/sql", query, token, raw=True, timeout=5)
        if code != 200:
            return None
        res = json.loads(body)[-1]
        names = [col["name"]["some"] for col in res["schema"]["elements"]]
        return [dict(zip(names, row)) for row in res["rows"]]

    def revision():
        rows = q("SELECT revision FROM script WHERE name = 'skills'") or [{}]
        return rows[0].get("revision")

    def set_law(law, value):
        verify.refresh_lease(st)
        t0 = time.time()
        code, body = verify.http(f"/v1/database/{db}/call/set_world_law", [law, value], token, timeout=60)
        return {"law": law, "value": value, "code": code, "reply": body[:300], "t0": t0, "t1": time.time()}

    # The world clock every ~20 ms, for the tick gap around each call.
    ticks, stop = [], threading.Event()

    def sample():
        while not stop.is_set():
            rows = q("SELECT tick FROM clock WHERE id = 0")
            if rows:
                ticks.append((time.time(), int(rows[0]["tick"])))
            time.sleep(0.02)

    def gap(t0, t1):
        """The longest wall time (ms) the tick stood still in [t0, t1], by the samples."""
        w = [(t, k) for t, k in ticks if t0 <= t <= t1]
        worst, last_t, last_k = 0.0, None, None
        for t, k in w:
            if last_k is None or k != last_k:
                if last_t is not None:
                    worst = max(worst, t - last_t)
                last_t, last_k = t, k
        if w and last_t is not None:
            worst = max(worst, w[-1][0] - last_t)
        rate = (w[-1][1] - w[0][1]) / (w[-1][0] - w[0][0]) if len(w) > 1 and w[-1][0] > w[0][0] else 0.0
        return round(worst * 1000, 1), round(rate, 1), len(w)

    def cover_row():
        rows = q("SELECT * FROM cover_law WHERE id = 0")
        return rows[0] if rows else None

    def wait_in_force(want, after):
        """Poll `cover_law` until each field in `want` reads so (the cover in force), at most
        COVER_WAIT_S from `after`: (the first wall time it read so or None, the last row)."""
        end, row = after + COVER_WAIT_S, None
        while time.time() < end:
            row = cover_row()
            if row and all(abs(float(row[k]) - v) < 1e-4 if isinstance(v, float) else row[k] == v for k, v in want.items()):
                return time.time(), row
            time.sleep(0.02)
        return None, row

    original = {r["name"]: r["value"] for r in (q("SELECT name, value FROM law_override") or [])}
    cover = (q("SELECT * FROM cover_law") or [{}])[0]
    # A land made before cover-stall (`c83ee5d1`) keeps no ground source: switching cover on
    # regenerates it, stalling the tick, so this scenario needs a world made since.
    if not cover.get("cover_sight_on") and not q("SELECT id, chunks FROM cover_source WHERE id = 0"):
        c.check(s, "the world keeps its cover ground source (made at or after c83ee5d1)", False,
                "no cover_source row: this world was made before cover-stall; make a fresh island world")
        return
    fill = float(cover.get("cover_brush_min_fill", 0.6))
    new_fill = 0.5 if abs(fill - 0.5) > 1e-3 else 0.7
    shipped = {"cue_transport_on": "true", "near_tier_on": "true", "gaze_on": "false", "cover_sight_on": "false",
               "cover_brush_min_fill": f"{fill:g}", "turn_rate": "6"}
    touched = list(shipped)
    in_place = r"rules: law overrides laid over in place .*changed \[\"{law}\"\]; delivery {d} cover {c} gaze {g}"
    # What `cover_law` reads once each cover step is in force.
    in_force = {("cover_sight_on", "true"): {"cover_sight_on": True},
                ("cover_brush_min_fill", f"{new_fill:g}"): {"cover_sight_on": True, "cover_brush_min_fill": new_fill},
                ("cover_sight_on", "false"): {"cover_sight_on": False}}
    steps = [
        ("cue_transport_on", "false", "delivery", r"rules: cue_transport_on false near_tier_on true", None),
        ("near_tier_on", "false", "delivery", r"perception: on the untiered set after", "untiered"),
        ("near_tier_on", "true", "delivery", r"perception: on the tiered set after", "tiered"),
        ("cue_transport_on", "true", "delivery", r"rules: cue_transport_on true near_tier_on true", None),
        ("gaze_on", "true", "gaze", r"sight edge: my senses from the authority \(my_senses_v_2\)", None),
        ("gaze_on", "false", "gaze", r"sight edge: my senses from the authority \(my_senses\)", None),
        ("cover_sight_on", "true", "cover", r"sight field: cover policy Some\(", None),
        ("cover_brush_min_fill", f"{new_fill:g}", "cover", rf"sight field: cover policy Some\(.*brush_min_fill: {new_fill:g}\b", None),
        ("cover_sight_on", "false", "cover", r"sight field: cover policy None", None),
    ]
    plan = "ready;wait:2;sync:armed;wait:1;dump:before;sync:toggled;dump:toggled;reconnect;wait:8;dump:reconnected;sync:done;quit"
    cmd = [sys.executable, os.path.join(HERE, "drive.py"), "--run", run, "--name", name, "--plan", plan, "--timeout", "900"]
    os.makedirs(base, exist_ok=True)
    seen_path = os.path.join(base, f"{name}.seen.jsonl")
    env = dict(os.environ, LIVING_GAME_SEEN_LOG=seen_path)
    results, installs = [], []
    sampler = threading.Thread(target=sample, daemon=True)
    sampler.start()
    drive_log = open(os.path.join(base, f"{name}.drive.log"), "w")
    fresh_log(out)
    p = subprocess.Popen(cmd, stdout=drive_log, stderr=subprocess.STDOUT, env=env)

    def wait_for(pattern, secs):
        end = time.time() + secs
        while time.time() < end and p.poll() is None:
            if re.search(pattern, log(out)):
                return True
            time.sleep(0.2)
        return False

    def go(sync):
        open(os.path.join(out, f"{sync}.go"), "w").close()

    try:
        if not wait_for(r"live script: waiting for \S*/armed\.go", 400):
            c.check(s, "the client reached the toggles", False, f"drive exit {p.poll()}")
            return
        go("armed")
        time.sleep(4)
        quiet = gap(time.time() - 3.5, time.time())
        for law, value, cls, effect, _ in steps:
            rev = revision()
            r = set_law(law, value)
            settled = r["t1"]
            if cls == "cover":
                # Judge the client's cover effect only once the authority holds it in force; the
                # next step (a brush edit after the switch-on) starts after this one completed.
                want = in_force[(law, value)]
                t_in, row = wait_in_force(want, r["t1"])
                r["in_force_want"], r["in_force_row"] = want, row
                r["in_force_at"] = t_in
                r["in_force_s"] = round(t_in - r["t1"], 3) if t_in else None
                settled = t_in or time.time()
            time.sleep(max(0.0, max(r["t1"] + 3.0, settled + 2.0) - time.time()))
            r.update(cls=cls, rev_before=rev, rev_after=revision())
            # The tick gap spans the call and, for cover, the whole derivation up to the row.
            r["gap_ms"], r["ticks_per_s"], r["samples"] = gap(r["t0"] - 0.5, settled + 1.5)
            results.append(r)
        for law, value in (("turn_rate", "6.5"), ("turn_rate", shipped["turn_rate"] if "turn_rate" not in original else original["turn_rate"])):
            rev = revision()
            r = set_law(law, value)
            time.sleep(4.0)
            r.update(rev_before=rev, rev_after=revision())
            r["gap_ms"], r["ticks_per_s"], r["samples"] = gap(r["t0"] - 0.5, r["t1"] + 2.5)
            installs.append(r)
        # The reconnect: the client on the tiered set (both delivery laws on, as it now knows
        # them) drops its connection, and while it is offline (it retries after 3 s) both laws
        # go off, so its first result after the reconnect holds rows it has not seen.
        t_reconnect = time.time()
        go("toggled")
        offline = wait_for(r"offline: ", 30)
        pre = [set_law("cue_transport_on", "false"), set_law("near_tier_on", "false")]
        wait_for(r"live script: waiting for \S*/done\.go", 60)
        go("done")
        p.wait(timeout=120)
        # A fresh client on the world with those overrides present.
        fresh_out, fresh_code, _ = drive(run, f"{s}-fresh", "ready;wait:3;dump:fresh;quit")
    finally:
        if p.poll() is None:
            p.terminate()
        for law in touched:
            set_law(law, original.get(law, shipped[law]))
        stop.set()
        drive_log.close()
    lines = timed_lines(out)
    frames = []
    if os.path.exists(seen_path):
        for line in open(seen_path):
            try:
                frames.append(json.loads(line))
            except ValueError:
                pass
    report = {"quiet_gap_ms": quiet, "steps": results, "installs": installs, "pre_reconnect": pre}
    c.check(s, "the world's tick ran between calls (quiet gap under 150 ms)", quiet[0] < 150, f"{quiet}")
    for r, (law, value, cls, effect, switch) in zip(results, steps):
        tag = f"{law}={value}"
        c.check(s, f"{tag}: set_world_law accepted", r["code"] == 200, r["reply"])
        c.check(s, f"{tag}: the script revision did not change", r["rev_before"] == r["rev_after"] and r["rev_before"] is not None, f"{r['rev_before']} -> {r['rev_after']}")
        pat = in_place.format(law=law, d=str(cls == "delivery").lower(), c=str(cls == "cover").lower(), g=str(cls == "gaze").lower())
        hit = first_after(lines, pat, r["t0"] - 0.05)
        eff = first_after(lines, effect, r["t0"] - 0.05)
        r["laid_over_ms"] = round((hit[0] - r["t1"]) * 1000, 1) if hit else None
        r["effect_ms"] = round((eff[0] - r["t1"]) * 1000, 1) if eff else None
        r["effect_line"] = eff[1] if eff else None
        c.check(s, f"{tag}: laid over in place as {cls}", hit is not None, pat)
        if cls == "cover":
            # The cover effect follows the `cover_law` row, not the override: within a second of
            # the row reading the change in force (polled, so the line may lead it by a poll).
            t_in = r.get("in_force_at")
            r["effect_after_in_force_ms"] = round((eff[0] - t_in) * 1000, 1) if eff and t_in else None
            ok = t_in is not None and eff is not None and eff[0] - t_in < 1.0
            detail = (f"cover in force after {r['in_force_s']} s; effect {r['effect_after_in_force_ms']} ms after it ({r['effect_ms']} ms after the reply)"
                      if t_in else f"cover_law did not read {r['in_force_want']} within {COVER_WAIT_S} s of the reply (last row {r['in_force_row']})")
            c.check(s, f"{tag}: the client reacted within a second of cover_law reading it in force ({effect})", ok, detail)
        else:
            c.check(s, f"{tag}: the client reacted within a second ({effect})", eff is not None and eff[0] - r["t1"] < 1.0, f"{r['effect_ms']} ms")
        c.check(s, f"{tag}: no compile on the client", first_after(lines, r"rules: skill script revision \d+ compiled", r["t0"] - 0.05, r["t0"] + 3.0) is None)
        c.check(s, f"{tag}: no world freeze (tick gap under 150 ms)", r["gap_ms"] < 150, f"{r['gap_ms']} ms")
        if switch:
            sub = first_after(lines, rf"perception: subscribing the {switch} set", r["t0"] - 0.05)
            r["missing_line"] = eff[1] if eff else None
            c.check(s, f"{tag}: the {switch} set subscribed beside the old one and applied", sub is not None and eff is not None)
            c.check(s, f"{tag}: the client's switch line lists nobody missing", bool(eff) and "missing now []" in eff[1], eff[1] if eff else "")
            # Frame by frame: each creature in the reads just before the call and 1 s after the
            # switch is in every frame between.
            if eff:
                # From the call on: "kept" is what the last frame before the call held, so a creature
                # coming into sight just before it is not missing from the frames before that.
                t0_ms, t1_ms = r["t0"] * 1000, (eff[0] + 1.0) * 1000
                before = [f for f in frames if f.get("wall_ms", 0) < r["t0"] * 1000]
                after = [f for f in frames if f.get("wall_ms", 0) >= t1_ms]
                ids = lambda f: {row[0] for row in f.get("rows", [])}
                keep = (ids(before[-1]) & ids(after[0])) if before and after else set()
                window = [f for f in frames if t0_ms <= f.get("wall_ms", 0) <= t1_ms]
                gaps = [f["wall_ms"] for f in window if keep - ids(f)]
                r["frames"], r["kept"], r["frames_missing"] = len(window), len(keep), len(gaps)
                sets = {f.get("reads") for f in window}
                c.check(s, f"{tag}: no frame without a creature kept across the switch", window and keep and not gaps,
                        f"{len(window)} frames, {len(keep)} kept, {len(gaps)} with one missing; reads {sets}")
    for r in installs:
        tag = f"turn_rate={r['value']} (full install)"
        comp = first_after(lines, rf"rules: skill script revision {r['rev_after']} compiled \(\d+ skills, \d+ law overrides\)", r["t0"] - 0.05)
        r["compiled_ms"] = round((comp[0] - r["t1"]) * 1000, 1) if comp else None
        c.check(s, f"{tag}: a new script revision", r["code"] == 200 and r["rev_after"] == (r["rev_before"] or 0) + 1, f"{r['rev_before']} -> {r['rev_after']} {r['reply']}")
        c.check(s, f"{tag}: compiled here with the overrides", comp is not None, comp[1] if comp else "")
        c.check(s, f"{tag}: the perception set kept (no subscribe after the compile)", first_after(lines, r"perception: subscribing", r["t0"] - 0.05, r["t0"] + 4.0) is None)
    after = [(t, x) for t, x in lines if t >= t_reconnect]
    subscribed = [x for _, x in after if x.startswith("perception: subscribing")]
    world = [x for _, x in after if x.startswith("world subscribed after")]
    down = [t for t, x in after if x.startswith("offline: ")]
    report["reconnect"] = {"subscribed": subscribed, "world": world, "offline": bool(offline), "laws_set_while_offline": pre,
                           "set_before_reconnect": bool(down) and all(r["t1"] < next((t for t, x in after if x.startswith("world subscribed after")), 0) for r in pre)}
    c.check(s, "reconnect: the delivery laws went off while the client was offline", report["reconnect"]["set_before_reconnect"] and all(r["code"] == 200 for r in pre), f"{report['reconnect']}")
    c.check(s, "reconnect: the base set came back with the overrides", any("law overrides)" in x for x in world), f"{world}")
    c.check(s, "reconnect: the first set chosen is the one the new rows choose (untiered), no tiered set first",
            bool(subscribed) and "untiered" in subscribed[0] and not any("the tiered set" in x for x in subscribed), f"{subscribed}")
    flog = log(fresh_out)
    fsub = re.findall(r"perception: subscribing the (\w+) set", flog)
    fcomp = re.findall(r"rules: skill script revision \d+ compiled \(\d+ skills, (\d+) law overrides\)", flog)
    report["fresh"] = {"exit": fresh_code, "subscribed": fsub, "compiled_with": fcomp}
    c.check(s, "fresh client: compiled with the world's overrides", bool(fcomp) and int(fcomp[0]) >= 2, f"{fcomp}")
    c.check(s, "fresh client: only the untiered set subscribed", fsub == ["untiered"], f"{fsub}")
    json.dump(report, open(os.path.join(base, f"{name}.json"), "w"), indent=1)


# The world's delivery laws in the order the client's `rules:` line names them (`net::perception_law`).
DELIVERY_LAWS = ("cue_transport_on", "near_tier_on", "motion_tables_on", "characters_table_on", "fighter_tables_on", "combat_feed_on")
# The two laws combat-switches adds to the client's switch (docs/BATTLE_VIEWERS.md, addenda 4 and 5).
COMBAT_LAWS = ("fighter_tables_on", "combat_feed_on")


def shipped_law(name):
    """A law's value in the shipped script's law block (`living/scripts/skills.rhai`), as JSON text."""
    m = re.search(rf"^\s*{name}:\s*(true|false),", open(os.path.join(ROOT, "living/scripts/skills.rhai")).read(), re.M)
    return m.group(1) if m else None


def owner_rows(run, query):
    """Owner SQL over HTTP straight to the world (fast enough to poll): rows as dicts, or None."""
    st = verify.load(run)
    code, body = verify.http(f"/v1/database/{st['db']}/sql", query, verify.admin_token(), raw=True, timeout=5)
    if code != 200:
        return None
    res = json.loads(body)[-1]
    names = [col["name"]["some"] for col in res["schema"]["elements"]]
    return [dict(zip(names, row)) for row in res["rows"]]


def feed_of(laws):
    """The perception set the client chooses (`net::Delivery::feed`): (tier, motion table,
    characters table, fighter table, combat feed). A law the world never set is read as shipped."""
    on = lambda k: laws.get(k, shipped_law(k)) == "true"
    return ("tiered" if on("cue_transport_on") or on("near_tier_on") else "untiered", on("motion_tables_on"), on("characters_table_on"),
            on("fighter_tables_on"), on("combat_feed_on"))


def tables_line(feed):
    """The `tables: …;` part of the client's perception lines for a set (`net::Feed::tables`)."""
    tier, m, ch, f, cf = feed
    b = lambda x: str(x).lower()
    # Since experience-incremental the client names the lines table after the combat feed
    # (`lines true|false`), and since heed-client ` throng true` after that while heed is on.
    return rf"tables: motion {b(m)} characters {b(ch)} fighters {b(f)} combat_feed {b(cf)} lines (?:true|false)(?: throng true)?;"


def seen_tables(feed):
    """The seen log's `tables` for a set (the reads)."""
    tier, m, ch, f, cf = feed
    return {"motion": m, "characters": ch, "fighters": f, "combat_feed": cf}


def reads_match(tables, feed):
    """The seen log's `tables` hold the reads `seen_tables` names for the set. The log names more
    than these switches set (since experience-incremental `lines`, the lines law's, which these
    scenarios leave as the world has it), so only the four are compared."""
    want = seen_tables(feed)
    return {k: tables.get(k) for k in want} == want


def set_on_line(feed):
    return rf"perception: on the {feed[0]} set after \d+ ms \(" + tables_line(feed)


def set_sub_line(feed):
    return rf"perception: subscribing the {feed[0]} set \(\d+ queries; " + tables_line(feed)


def identity_of(out):
    m = re.search(r"connected as ([0-9a-f]{64})", log(out))
    return m.group(1) if m else None


@scenario("battle-views", explicit=True)
def battle_views(run, c):
    """battle-views' client switch (docs/BATTLE_VIEWERS.md, "Rollout"): while one client plays, the
    two table laws (`motion_tables_on`, `characters_table_on`) and the two frame laws are set
    through `law_override` rows alone, through all four table-law combinations in both frame-tier
    states (and each tiered state's way: cues only, tiers only, both). For each step: the call
    accepted with the script revision unchanged, laid over in place as delivery, the client's set
    switched before broken when the set changes (the new set subscribed beside the old, nobody and
    no character missing in its line or in any frame: `LIVING_GAME_SEEN_LOG`) and not at all when
    it does not, the reads on the tables the laws name, and the tick never standing still. A
    table law going off is the kill switch by row: within a second the authority's public rows are
    gone (motion: moved back to the private tables, none split; the mirror: deleted), while the
    client keeps drawing until the views are in. Then a reconnect with both table laws on (the
    tables set first, no view set before it) and a fresh client. The four laws are restored from
    the world's own values (`law_values.own_laws`), else the shipped ones."""
    import threading
    s = "battle-views"
    st = verify.load(run)
    db, token = st["db"], verify.admin_token()
    name = f"{s}-{THEME}" if THEME else s
    base = os.path.join(ROOT, ".local/living/verify", run, "ui")
    out = os.path.join(base, name)
    q = lambda query: owner_rows(run, query)

    def revision():
        return ((q("SELECT revision FROM script WHERE name = 'skills'") or [{}])[0]).get("revision")

    def set_law(law, value):
        verify.refresh_lease(st)
        t0 = time.time()
        code, body = verify.http(f"/v1/database/{db}/call/set_world_law", [law, value], token, timeout=60)
        return {"law": law, "value": value, "code": code, "reply": body[:300], "t0": t0, "t1": time.time()}

    ticks, stop = [], threading.Event()

    def sample():
        while not stop.is_set():
            rows = q("SELECT tick FROM clock WHERE id = 0")
            if rows:
                ticks.append((time.time(), int(rows[0]["tick"])))
            time.sleep(0.02)

    def gap(t0, t1):
        w = [(t, k) for t, k in ticks if t0 <= t <= t1]
        worst, last_t, last_k = 0.0, None, None
        for t, k in w:
            if last_k is None or k != last_k:
                if last_t is not None:
                    worst = max(worst, t - last_t)
                last_t, last_k = t, k
        if w and last_t is not None:
            worst = max(worst, w[-1][0] - last_t)
        rate = (w[-1][1] - w[0][1]) / (w[-1][0] - w[0][0]) if len(w) > 1 and w[-1][0] > w[0][0] else 0.0
        return round(worst * 1000, 1), round(rate, 1)

    def copies(ident):
        """My copies where the authority holds them: public motion rows, private motion rows, mirror rows, projections."""
        x = f"0x{ident}"
        n = lambda query: len(q(query) or [])
        return {"public": n(f"SELECT body FROM seen_body_copy WHERE viewer = {x}"),
                "private": n(f"SELECT id FROM motion_seen WHERE viewer = {x}") + n(f"SELECT id FROM motion_near WHERE viewer = {x}"),
                "public_all": n("SELECT body FROM seen_body_copy"),
                "mirror": n(f"SELECT id FROM seen_character_copy WHERE viewer = {x}"),
                "mirror_all": n("SELECT id FROM seen_character_copy"),
                "projected": n(f"SELECT id FROM projected WHERE viewer = {x}")}

    original = own_laws(lambda x: sql(run, x))
    shipped = {k: shipped_law(k) for k in DELIVERY_LAWS}
    state = {k: original.get(k, shipped[k]) for k in DELIVERY_LAWS}
    start = dict(state)
    # Both table laws off first (on by default since bv-defaults-on; a step that changes nothing
    # is checked as kept), so the sequence reaches all eight combinations from any start.
    steps = [("motion_tables_on", "false"), ("characters_table_on", "false"),
             ("motion_tables_on", "true"), ("characters_table_on", "true"),
             ("motion_tables_on", "false"), ("motion_tables_on", "true"),
             ("characters_table_on", "false"), ("characters_table_on", "true"),
             ("cue_transport_on", "false"), ("near_tier_on", "false"),
             ("motion_tables_on", "false"), ("characters_table_on", "false"),
             ("motion_tables_on", "true"), ("characters_table_on", "true"),
             ("cue_transport_on", "true"), ("near_tier_on", "true")]
    c.check(s, "the world starts with both frame laws on", feed_of(start)[0] == "tiered", json.dumps(start))
    plan = "ready;wait:2;sync:armed;wait:1;dump:before;sync:toggled;dump:toggled;reconnect;wait:8;dump:reconnected;sync:done;quit"
    cmd = [sys.executable, os.path.join(HERE, "drive.py"), "--run", run, "--name", name, "--plan", plan, "--timeout", "900"]
    os.makedirs(base, exist_ok=True)
    seen_path = os.path.join(base, f"{name}.seen.jsonl")
    env = dict(os.environ, LIVING_GAME_SEEN_LOG=seen_path)
    results = []
    sampler = threading.Thread(target=sample, daemon=True)
    sampler.start()
    drive_log = open(os.path.join(base, f"{name}.drive.log"), "w")
    fresh_log(out)
    p = subprocess.Popen(cmd, stdout=drive_log, stderr=subprocess.STDOUT, env=env)

    def wait_for(pattern, secs):
        end = time.time() + secs
        while time.time() < end and p.poll() is None:
            if re.search(pattern, log(out)):
                return True
            time.sleep(0.2)
        return False

    def go(sync):
        open(os.path.join(out, f"{sync}.go"), "w").close()

    fresh_out, fresh_code, ident = None, None, None
    try:
        if not wait_for(r"live script: waiting for \S*/armed\.go", 400):
            c.check(s, "the client reached the toggles", False, f"drive exit {p.poll()}")
            return
        ident = identity_of(out)
        go("armed")
        time.sleep(4)
        quiet = gap(time.time() - 3.5, time.time())
        for law, value in steps:
            before = feed_of(state)
            state[law] = value
            after = feed_of(state)
            rev = revision()
            r = set_law(law, value)
            r.update(before=before, after=after, state=dict(state))
            # The kill switch: how soon the authority's public rows of that table are gone.
            if value == "false" and law in ("motion_tables_on", "characters_table_on"):
                table = "seen_body_copy" if law == "motion_tables_on" else "seen_character_copy"
                gone = None
                while time.time() - r["t1"] < 3.0:
                    rows = q(f"SELECT viewer FROM {table}")
                    if rows == []:
                        gone = round((time.time() - r["t1"]) * 1000, 1)
                        break
                    time.sleep(0.02)
                r["empty_after_ms"] = gone
            time.sleep(3.0)
            r["rev_before"], r["rev_after"] = rev, revision()
            r["gap_ms"], r["ticks_per_s"] = gap(r["t0"] - 0.5, r["t1"] + 1.5)
            r["copies"] = copies(ident) if ident else None
            results.append(r)
        # The reconnect with both table laws on: the client's first set after it is the tables set.
        t_reconnect = time.time()
        go("toggled")
        offline = wait_for(r"offline: ", 30)
        wait_for(r"live script: waiting for \S*/done\.go", 60)
        go("done")
        p.wait(timeout=120)
        fresh_out, fresh_code, _ = drive(run, f"{s}-fresh", "ready;wait:4;dump:fresh;quit", env={"LIVING_GAME_SEEN_LOG": os.path.join(base, f"{name}-fresh.seen.jsonl")})
    finally:
        if p.poll() is None:
            p.terminate()
        for law in DELIVERY_LAWS:
            set_law(law, original.get(law, shipped[law]))
        stop.set()
        drive_log.close()
    lines = timed_lines(out)
    frames = []
    if os.path.exists(seen_path):
        for line in open(seen_path):
            try:
                frames.append(json.loads(line))
            except ValueError:
                pass
    report = {"identity": ident, "start": start, "quiet_gap_ms": quiet, "steps": results}
    c.check(s, "the world's tick ran between calls (quiet gap under 150 ms)", quiet[0] < 150, f"{quiet}")
    in_place = r"rules: law overrides laid over in place .*changed \[\"{law}\"\]; delivery true cover false gaze false"
    ids = lambda f: {row[0] for row in f.get("rows", [])}
    chars = lambda f: set(f.get("characters", []))
    for r in results:
        law, value, before, after = r["law"], r["value"], tuple(r["before"]), tuple(r["after"])
        tag = f"{law}={value} ({after[0]}, motion table {after[1]}, characters table {after[2]})"
        c.check(s, f"{tag}: set_world_law accepted", r["code"] == 200, r["reply"])
        c.check(s, f"{tag}: the script revision did not change", r["rev_before"] == r["rev_after"] and r["rev_before"] is not None, f"{r['rev_before']} -> {r['rev_after']}")
        hit = first_after(lines, in_place.format(law=law), r["t0"] - 0.05, r["t0"] + 3.0)
        r["laid_over_ms"] = round((hit[0] - r["t1"]) * 1000, 1) if hit else None
        c.check(s, f"{tag}: laid over in place as delivery", hit is not None)
        c.check(s, f"{tag}: no world freeze (tick gap under 150 ms)", r["gap_ms"] < 150, f"{r['gap_ms']} ms")
        if after == before:
            eff = first_after(lines, "rules: " + " ".join(f"{k} {r['state'][k]}" for k in DELIVERY_LAWS), r["t0"] - 0.05, r["t0"] + 3.0)
            r["effect_ms"] = round((eff[0] - r["t1"]) * 1000, 1) if eff else None
            c.check(s, f"{tag}: the client read the law within a second", eff is not None and eff[0] - r["t1"] < 1.0, f"{r['effect_ms']} ms")
            c.check(s, f"{tag}: the set kept (no subscribe)", first_after(lines, r"perception: subscribing", r["t0"] - 0.05, r["t0"] + 3.0) is None)
            continue
        sub = first_after(lines, set_sub_line(after), r["t0"] - 0.05)
        eff = first_after(lines, set_on_line(after), r["t0"] - 0.05)
        r["effect_ms"] = round((eff[0] - r["t1"]) * 1000, 1) if eff else None
        r["switch_line"] = eff[1] if eff else None
        c.check(s, f"{tag}: the new set subscribed beside the old and the reads moved to it within 1.5 s", sub is not None and eff is not None and eff[0] - r["t1"] < 1.5, f"{r['effect_ms']} ms")
        c.check(s, f"{tag}: the switch line lists nobody and no character missing", bool(eff) and eff[1].count("missing now []") == 3, eff[1] if eff else "")
        if eff:
            # From the call on: "kept" is what the last frame before the call held, so a creature
            # coming into sight just before it is not missing from the frames before that.
            t0_ms, t1_ms = r["t0"] * 1000, (eff[0] + 1.0) * 1000
            pre = [f for f in frames if f.get("wall_ms", 0) < r["t0"] * 1000]
            post = [f for f in frames if f.get("wall_ms", 0) >= t1_ms]
            keep = (ids(pre[-1]) & ids(post[0])) if pre and post else set()
            keep_c = (chars(pre[-1]) & chars(post[0])) if pre and post else set()
            window = [f for f in frames if t0_ms <= f.get("wall_ms", 0) <= t1_ms]
            gaps = [f["wall_ms"] for f in window if keep - ids(f)]
            gaps_c = [f["wall_ms"] for f in window if keep_c - chars(f)]
            r["frames"], r["kept"], r["kept_characters"], r["frames_missing"], r["frames_missing_characters"] = len(window), len(keep), len(keep_c), len(gaps), len(gaps_c)
            c.check(s, f"{tag}: no frame without a creature or a character kept across the switch", window and keep and keep_c and not gaps and not gaps_c,
                    f"{len(window)} frames, {len(keep)} kept ({len(gaps)} frames missing one), {len(keep_c)} characters kept ({len(gaps_c)} frames missing one)")
            tables = post[0].get("tables", {}) if post else {}
            c.check(s, f"{tag}: the reads take the tables the laws name", post and post[0].get("reads") == after[0] and reads_match(tables, after), json.dumps(tables))
        cp = r["copies"] or {}
        if law == "motion_tables_on":
            if value == "true":
                c.check(s, f"{tag}: my motion copies all in seen_body_copy, none left private", cp.get("public", 0) > 0 and cp.get("private") == 0, json.dumps(cp))
            else:
                c.check(s, f"{tag}: the kill switch: seen_body_copy empty within a second, my copies back in the private tables, none split",
                        r.get("empty_after_ms") is not None and r["empty_after_ms"] < 1000 and cp.get("public_all") == 0 and cp.get("private", 0) > 0, f"empty after {r.get('empty_after_ms')} ms; {json.dumps(cp)}")
        if law == "characters_table_on":
            if value == "true":
                c.check(s, f"{tag}: my mirror whole (a row per projection)", cp.get("mirror", 0) > 0 and cp.get("mirror") == cp.get("projected"), json.dumps(cp))
            else:
                c.check(s, f"{tag}: the kill switch: seen_character_copy empty within a second",
                        r.get("empty_after_ms") is not None and r["empty_after_ms"] < 1000 and cp.get("mirror_all") == 0, f"empty after {r.get('empty_after_ms')} ms; {json.dumps(cp)}")
    combos = sorted({tuple(r["after"][:3]) for r in results} | {feed_of(start)[:3]})
    report["combinations"] = combos
    c.check(s, "every table-law combination ran in both frame-tier states", len(combos) == 8, json.dumps(combos))
    final = feed_of({**start, **{r["law"]: r["value"] for r in results}})
    after_rc = [(t, x) for t, x in lines if t >= t_reconnect]
    subscribed = [x for _, x in after_rc if x.startswith("perception: subscribing")]
    report["reconnect"] = {"offline": bool(offline), "subscribed": subscribed}
    c.check(s, "reconnect with both table laws on: the client went offline and came back", bool(offline) and any(x.startswith("world subscribed after") for _, x in after_rc))
    c.check(s, "reconnect: the first set chosen reads both tables, no view set before it",
            bool(subscribed) and re.search(set_sub_line(final), subscribed[0]) is not None and all("tables: motion true characters true" in x for x in subscribed), f"{subscribed}")
    c.check(s, "reconnect: the reads moved to the tables", first_after(lines, set_on_line(final), t_reconnect) is not None)
    flog = log(fresh_out) if fresh_out else ""
    fsub = re.findall(r"perception: subscribing the .*", flog)
    report["fresh"] = {"exit": fresh_code, "subscribed": fsub}
    c.check(s, "fresh client with both table laws on: only the tables set subscribed, and read", len(fsub) == 1 and re.search(set_sub_line(final), fsub[0]) is not None and re.search(set_on_line(final), flog) is not None, f"{fsub}")
    c.check(s, "the four laws restored to the world's own values", {k: own_laws(lambda x: sql(run, x)).get(k, shipped[k]) for k in DELIVERY_LAWS} == {k: original.get(k, shipped[k]) for k in DELIVERY_LAWS})
    json.dump(report, open(os.path.join(base, f"{name}.json"), "w"), indent=1)


@scenario("battle-views-ui", explicit=True)
def battle_views_ui(run, c):
    """camera, talk and far with both table laws on (docs/BATTLE_VIEWERS.md, "Rollout" step 5):
    each scenario's checks, and every client those scenarios started read both tables (its switch
    line names them, and no view set was read). The table laws are put back after."""
    s = "battle-views-ui"
    original = own_laws(lambda x: sql(run, x))
    shipped = {k: shipped_law(k) for k in DELIVERY_LAWS}
    t0 = time.time()
    try:
        for law in ("motion_tables_on", "characters_table_on"):
            call_admin(run, "set_world_law", [law, "true"], check=True)
        laws = own_laws(lambda x: sql(run, x))
        c.check(s, "both table laws read on in law_override", laws.get("motion_tables_on") == "true" and laws.get("characters_table_on") == "true", json.dumps({k: laws.get(k) for k in DELIVERY_LAWS}))
        for name in ("camera", "talk", "far"):
            SCENARIOS[name](run, c)
        laws = own_laws(lambda x: sql(run, x))
        c.check(s, "both table laws still on after the scenarios (far's script install kept them)", laws.get("motion_tables_on") == "true" and laws.get("characters_table_on") == "true", json.dumps({k: laws.get(k) for k in DELIVERY_LAWS}))
    finally:
        for law in ("motion_tables_on", "characters_table_on"):
            call_admin(run, "set_world_law", [law, original.get(law, shipped[law])], check=True)
    logs = [p for p in glob.glob(os.path.join(ROOT, ".local/living/verify", run, "ui", "*", "client.log")) if os.path.getmtime(p) >= t0]
    on = []
    for p in sorted(logs):
        t = log(os.path.dirname(p))
        if "playing character" not in t:
            continue
        reads = re.findall(r"perception: on the \w+ set after \d+ ms \(tables: motion (\w+) characters (\w+) ", t)
        on.append((os.path.basename(os.path.dirname(p)), reads))
    bad = [(n, r) for n, r in on if not r or any(x != ("true", "true") for x in r)]
    c.check(s, f"every client of camera, talk and far read both tables ({len(on)} clients)", on and not bad, json.dumps(bad or [n for n, _ in on]))
    json.dump({"clients": on}, open(os.path.join(ROOT, ".local/living/verify", run, "ui", "battle-views-ui.json"), "w"), indent=1)


class ByteRelay:
    """A TCP relay in front of the authority for the client alone, counting what the server sends
    each connection (the client's subscription traffic on the wire), sampled every 0.5 s."""

    def __init__(self, upstream_port):
        import socket, threading
        self.socket, self.threading = socket, threading
        self.up = upstream_port
        self.ls = socket.socket()
        self.ls.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.ls.bind(("127.0.0.1", 0))
        self.ls.listen(8)
        self.port = self.ls.getsockname()[1]
        self.down = []
        self.samples = []
        self.done = threading.Event()
        threading.Thread(target=self.accept, daemon=True).start()
        threading.Thread(target=self.sample, daemon=True).start()

    def accept(self):
        while not self.done.is_set():
            try:
                cl, _ = self.ls.accept()
            except OSError:
                return
            up = self.socket.create_connection(("127.0.0.1", self.up))
            i = len(self.down)
            self.down.append(0)
            self.threading.Thread(target=self.pipe, args=(up, cl, i), daemon=True).start()
            self.threading.Thread(target=self.pipe, args=(cl, up, None), daemon=True).start()

    def pipe(self, a, b, i):
        try:
            while True:
                d = a.recv(65536)
                if not d:
                    break
                if i is not None:
                    self.down[i] += len(d)
                b.sendall(d)
        except OSError:
            pass
        for x in (a, b):
            try:
                x.shutdown(self.socket.SHUT_RDWR)
            except OSError:
                pass

    def sample(self):
        while not self.done.is_set():
            self.samples.append((time.time(), sum(self.down)))
            time.sleep(0.5)

    def bytes_between(self, t0, t1):
        s0 = max((b for t, b in self.samples if t <= t0), default=0)
        s1 = max((b for t, b in self.samples if t <= t1), default=0)
        return s1 - s0

    def close(self):
        self.done.set()
        self.ls.close()


# Where `battle-views-cost` stands the player: the island newcomer's arrival on Brackenford's
# square, among residents (where a play-test starts), and a quiet open spot (look-walk's).
BV_PLACES = (("square", (412.5, 256.5)), ("open", (300.0, 330.0)))


def walker_ages(frames, walker, w0, w1):
    """Near ages of a walker's fresh segments in a seen log: for each newer `t_ms` of it in the
    reads, the first frame holding it less its `t_ms` (ms), in [w0, w1] (s). A re-entry into
    sight (absent the frame before) is not a fresh segment, as gate_load's sampler counts."""
    ages, last, present = [], None, False
    for f in frames:
        t = next((t for i, t in f.get("rows", []) if i == walker), None)
        inside = w0 <= f.get("wall_ms", 0) / 1000 <= w1
        if t is not None and present and last is not None and t > last and inside:
            ages.append(f["wall_ms"] - t)
        if t is not None:
            last = t if last is None else max(last, t)
        present = t is not None
    return sorted(ages)


@scenario("battle-views-cost", explicit=True)
def battle_views_cost(run, c):
    """kB/s and near p90 with both table laws on against off (docs/BATTLE_VIEWERS.md, "Rollout"
    step 7), on the real client, at two places (`BV_PLACES`): Brackenford's square among its
    residents (as a play-test), and a quiet open spot. At each, four drives, off, on, off, on,
    each with the client's connection through a byte-counting relay (`LIVING_GAME_CLIENT_SERVER`)
    and a second player (verify.py's player identity) placed 1.2 m from it walking a small
    octagon (a new `human_move` every 0.75 s for 40 s), as frame-views' near-age fixture did.
    kB/s: what the server sent the client in that window, less its first second. Near age: for
    each fresh segment of the walker, the first frame whose reads hold it (`LIVING_GAME_SEEN_LOG`)
    less its `t_ms`, so frame-quantized alike in both arms; re-entries into sight are left out
    (`walker_ages`), and the time the walker was out of sight is reported. The admin moves only
    the two players (`place_at`), and puts both back after; no resident is moved. The table laws
    are put back after."""
    summary = delivery_cost(run, c, "battle-views-cost", ("motion_tables_on", "characters_table_on"), "battle-views-cost")
    json.dump(summary, open(os.path.join(ROOT, ".local/living/verify", run, "ui", "battle-views-cost.json"), "w"), indent=1)


# The seen log's `tables` key for each delivery law with a table (`net::seen_log`).
SEEN_KEY = {"motion_tables_on": "motion", "characters_table_on": "characters", "fighter_tables_on": "fighters", "combat_feed_on": "combat_feed"}


def delivery_cost(run, c, s, laws, prefix, fight=False):
    """`battle-views-cost`'s measurement for `laws` set together on against off (see its doc).
    With `fight`, every third move my own player identity (the client's token) asks a strike at
    no one, which the rules refuse: a refusal is a combat feed row for me alone
    (`combat::show_to`), no damage to anyone. The walker must have fought before (a `fighter` row
    lasts until death), so my fighter reads hold it. It does not jump: a jump puts no row in an
    onlooker's feed, and one jump left a walker rooted for good (an authority gap, the
    combat-switches record). The arm reports the combat rows the client took and the fighters it
    read."""
    st = verify.load(run)
    db = st["db"]
    upstream = int(re.search(r":(\d+)", os.environ.get("LIVING_STDB_URL", "http://127.0.0.1:3300")).group(1))
    original = own_laws(lambda x: sql(run, x))
    shipped = {k: shipped_law(k) for k in DELIVERY_LAWS}

    def body():
        r = subprocess.run([sys.executable, V, "sql", "--run", run, "SELECT id FROM my_body", "--as-player"], capture_output=True, text=True)
        rows = json.loads(r.stdout[r.stdout.find("["):]) if "[" in r.stdout else []
        return rows[0]["id"] if rows else None
    walker = body()
    if walker is None:
        subprocess.run([sys.executable, V, "player", "--run", run, "join", "Walker"], capture_output=True, text=True)
        walker = body()
    c.check(s, "a second player to walk beside me", walker is not None)
    if walker is None:
        return
    st = verify.load(run)
    if fight and not owner_rows(run, f"SELECT id FROM fighter WHERE id = {walker}"):
        # One guard raised (no damage), so the walker has a `fighter` row for my reads.
        verify.http(f"/v1/database/{db}/call/use_skill", ["block", 0, 0.0, 0.0], st["token"], timeout=5)
        time.sleep(1.0)
    dirs = [(math.cos(math.radians(a)), math.sin(math.radians(a))) for a in range(0, 360, 45)]
    walker_at = (sql(run, f"SELECT x, y FROM body WHERE id = {walker}") or [None])[0]

    def walk(stop_at, sent, jumps):
        i = 0
        while time.time() < stop_at:
            dx, dy = dirs[i % 8]
            code, _ = verify.http(f"/v1/database/{db}/call/human_move", [dx, dy, False], st["token"], timeout=5)
            sent.append((time.time(), code))
            if fight and i % 3 == 1:
                jc, _ = verify.http(f"/v1/database/{db}/call/use_skill", ["strike", 0, 0.0, 0.0], my_token(), timeout=5)
                jumps.append(jc)
            i += 1
            time.sleep(max(0.0, 0.75 - (time.time() - sent[-1][0])))
        verify.http(f"/v1/database/{db}/call/human_move", [0, 0, False], st["token"], timeout=5)

    pct = lambda v, p: v[min(len(v) - 1, max(0, math.ceil(p * len(v)) - 1))] if v else None
    me_before = None
    # My client's token, written by its first connection (read at the walk, once a drive is on).
    my_token = lambda: open(os.path.join(ROOT, ".local/living/verify", run, "ui", "player.token")).read().strip()
    reads_of = lambda f: json.dumps({SEEN_KEY[k]: (f.get("tables") or {}).get(SEEN_KEY[k]) for k in laws}, sort_keys=True)
    tables = lambda on: json.dumps({SEEN_KEY[k]: on for k in laws}, sort_keys=True)
    arms = []
    try:
        for place, (px, py) in BV_PLACES:
            for k, on in enumerate((False, True, False, True)):
                for law in laws:
                    call_admin(run, "set_world_law", [law, "true" if on else "false"], check=True)
                name = f"{prefix}-{place}-{k}-{'on' if on else 'off'}"
                out = os.path.join(ROOT, ".local/living/verify", run, "ui", name)
                seen = os.path.join(ROOT, ".local/living/verify", run, "ui", f"{name}.seen.jsonl")
                relay = ByteRelay(upstream)
                env = dict(os.environ, LIVING_GAME_SEEN_LOG=seen, LIVING_GAME_CLIENT_SERVER=f"http://127.0.0.1:{relay.port}")
                plan = "ready;wait:2;sync:scene;sync:spot;wait:3;sync:near;wait:3;sync:walk;wait:43;quit"
                cmd = [sys.executable, os.path.join(HERE, "drive.py"), "--run", run, "--name", name, "--plan", plan, "--timeout", "600",
                       "--sync", f"spot=place_at|{{me}}|{px}|{py}", "--sync", f"near=place_at|{walker}|(mx+1.2)|(my)"]
                dlog = open(os.path.join(ROOT, ".local/living/verify", run, "ui", f"{name}.drive.log"), "w")
                fresh_log(out)
                p = subprocess.Popen(cmd, stdout=dlog, stderr=subprocess.STDOUT, env=env)
                sent, jumps, arm = [], [], {"arm": name, "place": place, "on": on}
                w0 = w1 = time.time()
                try:
                    end = time.time() + 400
                    while time.time() < end and p.poll() is None and not re.search(r"live script: waiting for \S*/walk\.go", log(out)):
                        time.sleep(0.2)
                    w0 = time.time()
                    open(os.path.join(out, "walk.go"), "w").close()
                    walk(w0 + 40, sent, jumps)
                    w1 = time.time()
                    p.wait(timeout=120)
                finally:
                    if p.poll() is None:
                        p.terminate()
                    dlog.close()
                    relay.close()
                sc = os.path.join(out, "scene.json")
                if me_before is None and os.path.exists(sc):
                    scene = json.load(open(sc))
                    me_before = (scene.get("me"), scene.get("me_at"))
                frames = [json.loads(l) for l in open(seen)] if os.path.exists(seen) else []
                window = [f for f in frames if w0 <= f.get("wall_ms", 0) / 1000 <= w1]
                ages = walker_ages(frames, walker, w0 + 1, w1)
                absent = [f for f in window if not any(i == walker for i, _ in f.get("rows", []))]
                kb = relay.bytes_between(w0 + 1, w1) / 1000 / max(1e-6, w1 - w0 - 1)
                reads = {reads_of(f) for f in window}
                others = sorted(len(f.get("rows", [])) for f in window)
                fighters = sorted(len(f.get("fighters", [])) for f in window)
                arm.update(kB_per_s=round(kb, 2), total_kB=round(sum(relay.down) / 1000, 1), segments=len(ages), near_p50=pct(ages, 0.5), near_p90=pct(ages, 0.9),
                           near_max=ages[-1] if ages else None, walker_absent_s=round(len(absent) / max(1, len(window)) * (w1 - w0), 1),
                           others_median=others[len(others) // 2] if others else None, fps=round(len(window) / max(1e-6, w1 - w0), 1),
                           moves=len(sent), moves_ok=sum(1 for _, x in sent if x == 200), reads=sorted(reads), connections=len(relay.down), exit=p.returncode,
                           refusals_asked=sum(1 for x in jumps if x == 200), combat_rows=sum(len(f.get("combat", [])) for f in window),
                           fighters_median=fighters[len(fighters) // 2] if fighters else None)
                arms.append(dict(arm, ages=ages))
                print(f"{s}: {json.dumps(arm)}", flush=True)
                c.check(s, f"{name}: the client ran, the walker walked{' and fought' if fight else ''}, the reads took the {'tables' if on else 'views'}",
                        p.returncode == 0 and arm["moves_ok"] >= 40 and arm["segments"] >= 10 and reads == {tables(on)} and (not fight or (arm["refusals_asked"] >= 5 and arm["combat_rows"] > 0 and (arm["fighters_median"] or 0) > 0)), json.dumps(arm))
    finally:
        for law in laws:
            call_admin(run, "set_world_law", [law, original.get(law, shipped[law])], check=True)
        # The two players back where they stood, so a later scenario finds the scene it expects.
        if me_before and me_before[0] is not None and me_before[1]:
            call_admin(run, "place_at", [int(me_before[0]), me_before[1][0], me_before[1][1]])
        if walker_at:
            call_admin(run, "place_at", [walker, walker_at["x"], walker_at["y"]])

    def pooled(place, on):
        mine = [a for a in arms if a["place"] == place and a["on"] == on]
        kbs = [a["kB_per_s"] for a in mine]
        ages = sorted(x for a in mine for x in a["ages"])
        return {"kB_per_s": round(sum(kbs) / len(kbs), 2) if kbs else None, "kB_per_s_arms": kbs, "segments": len(ages),
                "near_p50": pct(ages, 0.5), "near_p90": pct(ages, 0.9), "near_max": ages[-1] if ages else None,
                "near_p90_arms": [a["near_p90"] for a in mine], "walker_absent_s": [a["walker_absent_s"] for a in mine]}
    summary = {place: {"off": pooled(place, False), "on": pooled(place, True)} for place, _ in BV_PLACES}
    summary["laws"] = list(laws)
    summary["arms"] = arms
    print(f"{s}: " + json.dumps({k: v for k, v in summary.items() if k != "arms"}), flush=True)
    c.check(s, f"{'+'.join(laws)}: kB/s and near ages recorded for both arms at both places",
            all(summary[p][a]["kB_per_s"] and summary[p][a]["segments"] for p, _ in BV_PLACES for a in ("off", "on")), json.dumps({k: v for k, v in summary.items() if k != "arms"}))
    return summary


def second_player(run, name):
    """verify.py's player identity as a creature beside mine (joined once per run): its id."""
    def body():
        rows = sql_as_player(run, "SELECT id FROM my_body")
        return rows[0]["id"] if rows else None
    me = body()
    if me is None:
        subprocess.run([sys.executable, V, "player", "--run", run, "join", name], capture_output=True, text=True)
        me = body()
    return me


def seen_frames(path):
    frames = []
    if os.path.exists(path):
        for line in open(path):
            try:
                frames.append(json.loads(line))
            except ValueError:
                pass
    return frames


@scenario("combat-switches", explicit=True)
def combat_switches(run, c):
    """combat-switches' client switch (docs/BATTLE_VIEWERS.md, addenda 4 and 5, "Rollout"): while
    one client plays beside a fight, `fighter_tables_on` and `combat_feed_on` are set through
    `law_override` rows alone, each on, off (the kill switch) and on again, under the tiered and
    the untiered frame state and with the copy-table laws off and on. A second player (verify.py's
    player identity) strikes a resident held beside me just before and after each combat-feed
    call, so events are in flight across every switch. For each call: accepted, the script
    revision kept, laid over in place as delivery, the tick never standing still; when the set
    changes, the new set subscribed beside the old and the reads on it within 1.5 s, nobody, no
    character and no fighter missing in the switch line or in any frame (`LIVING_GAME_SEEN_LOG`),
    the reads on the tables the laws name; `fighter_tables_on` on: my fighter copies all in
    `seen_fighter_copy`, none private; off: the table empty within a second and my copies back in
    `fighter_seen`/`fighter_near`. Across the run: every `combat_seen` row the authority wrote for
    me (owner SQL polled every ~60 ms) was taken by the client, whichever source was in place.
    Then a reconnect with both laws on (the first set reads the fighter table and the feed, and
    `my_combat` is read once) and a fresh client. The six delivery laws are restored from the
    world's own values (`law_values.own_laws`), else the shipped ones; the resident by
    `resident_fixture`."""
    import threading
    s = "combat-switches"
    st = verify.load(run)
    db, token = st["db"], verify.admin_token()
    name = f"{s}-{THEME}" if THEME else s
    base = os.path.join(ROOT, ".local/living/verify", run, "ui")
    out = os.path.join(base, name)
    q = lambda query: owner_rows(run, query)
    # The two healthiest residents, held side by side; each strike goes to the healthier, and
    # none below `STRIKE_FLOOR` (a resident struck run after run would die: two strikes a
    # combat-feed call, 5 damage each).
    hp = lambda i: ((q(f"SELECT hp FROM vitals WHERE id = {i}") or [{}])[0]).get("hp") or 0
    pool = sorted(residents(run, 12), key=hp, reverse=True)[:2]
    targets = [i for i in pool if hp(i) >= STRIKE_FLOOR]
    target = targets[0] if targets else None
    striker = second_player(run, "Striker")
    c.check(s, "two healthy residents to strike and a second player to strike them", len(targets) == 2 and striker is not None, f"{[(i, hp(i)) for i in pool]} {striker}")
    if len(targets) < 2 or striker is None:
        return
    st = verify.load(run)   # the player identity's token, recorded when it joined

    def revision():
        return ((q("SELECT revision FROM script WHERE name = 'skills'") or [{}])[0]).get("revision")

    def set_law(law, value):
        verify.refresh_lease(st)
        t0 = time.time()
        code, body = verify.http(f"/v1/database/{db}/call/set_world_law", [law, value], token, timeout=60)
        return {"law": law, "value": value, "code": code, "reply": body[:300], "t0": t0, "t1": time.time()}

    strikes = []

    def strike():
        health = {i: hp(i) for i in targets}
        who = max(targets, key=lambda i: health[i])
        if health[who] < STRIKE_FLOOR:
            strikes.append({"t": time.time(), "code": None, "reply": f"skipped: {health}"})
            return
        at = (q(f"SELECT x, y FROM body WHERE id = {who}") or [None])[0]
        if not at:
            return
        code, body = verify.http(f"/v1/database/{db}/call/use_skill", ["strike", who, at["x"], at["y"]], st["token"], timeout=10)
        strikes.append({"t": time.time(), "target": who, "hp": health[who], "code": code, "reply": body[:120]})

    ticks, stop, ident_box, feed_rows = [], threading.Event(), [None], {}

    def sample():
        n = 0
        while not stop.is_set():
            rows = q("SELECT tick FROM clock WHERE id = 0")
            if rows:
                ticks.append((time.time(), int(rows[0]["tick"])))
            n += 1
            if ident_box[0] and n % 3 == 0:
                for r in q(f"SELECT id, kind, actor, target FROM combat_seen WHERE viewer = 0x{ident_box[0]}") or []:
                    feed_rows.setdefault(int(r["id"]), {"first": time.time(), **r})
            time.sleep(0.02)

    def gap(t0, t1):
        w = [(t, k) for t, k in ticks if t0 <= t <= t1]
        worst, last_t, last_k = 0.0, None, None
        for t, k in w:
            if last_k is None or k != last_k:
                if last_t is not None:
                    worst = max(worst, t - last_t)
                last_t, last_k = t, k
        if w and last_t is not None:
            worst = max(worst, w[-1][0] - last_t)
        return round(worst * 1000, 1)

    def fighter_copies(ident):
        x = f"0x{ident}"
        n = lambda query: len(q(query) or [])
        return {"public": n(f"SELECT id FROM seen_fighter_copy WHERE viewer = {x}"),
                "private": n(f"SELECT id FROM fighter_seen WHERE viewer = {x}") + n(f"SELECT id FROM fighter_near WHERE viewer = {x}"),
                "public_all": n("SELECT id FROM seen_fighter_copy")}

    original = own_laws(lambda x: sql(run, x))
    shipped = {k: shipped_law(k) for k in DELIVERY_LAWS}
    state = {k: original.get(k, shipped[k]) for k in DELIVERY_LAWS}
    start = dict(state)
    # Both new laws off first (a step that changes nothing is checked as kept), so the sequence is
    # the same from any start; then each alone and both, on and off, tiered; the frame laws off
    # (untiered) and the same; the copy-table laws off and on under both; the frame laws back.
    steps = [("fighter_tables_on", "false"), ("combat_feed_on", "false"),
             ("fighter_tables_on", "true"), ("combat_feed_on", "true"),
             ("fighter_tables_on", "false"), ("fighter_tables_on", "true"),
             ("combat_feed_on", "false"), ("combat_feed_on", "true"),
             ("motion_tables_on", "false"), ("characters_table_on", "false"),
             ("cue_transport_on", "false"), ("near_tier_on", "false"),
             ("fighter_tables_on", "false"), ("combat_feed_on", "false"),
             ("fighter_tables_on", "true"), ("combat_feed_on", "true"),
             ("motion_tables_on", "true"), ("characters_table_on", "true"),
             ("combat_feed_on", "false"), ("fighter_tables_on", "false"),
             ("combat_feed_on", "true"), ("fighter_tables_on", "true"),
             ("cue_transport_on", "true"), ("near_tier_on", "true")]
    c.check(s, "the world starts with both frame laws on", feed_of(start)[0] == "tiered", json.dumps(start))
    plan = "ready;wait:2;sync:scene;sync:near;wait:2;sync:armed;wait:1;dump:before;sync:toggled;dump:toggled;reconnect;wait:8;dump:reconnected;sync:done;quit"
    os.makedirs(base, exist_ok=True)
    seen_path = os.path.join(base, f"{name}.seen.jsonl")
    cmd = [sys.executable, os.path.join(HERE, "drive.py"), "--run", run, "--name", name, "--plan", plan, "--timeout", "900",
           "--place", f"{targets[0]}:1.6:0", "--place", f"{targets[1]}:1.6:1.2", "--sync", f"near=place_at|{striker}|(mx+2.4)|(my+0.6)"]
    env = dict(os.environ, LIVING_GAME_SEEN_LOG=seen_path)
    results = []
    sampler = threading.Thread(target=sample, daemon=True)
    fresh_out, fresh_code, ident, quiet, t_reconnect, offline = None, None, None, 0.0, time.time(), False
    report_held = {"public": 0, "private": 0}
    with resident_fixture(run, targets):
        sampler.start()
        drive_log = open(os.path.join(base, f"{name}.drive.log"), "w")
        fresh_log(out)
        p = subprocess.Popen(cmd, stdout=drive_log, stderr=subprocess.STDOUT, env=env)

        def wait_for(pattern, secs):
            end = time.time() + secs
            while time.time() < end and p.poll() is None:
                if re.search(pattern, log(out)):
                    return True
                time.sleep(0.2)
            return False

        def go(sync):
            open(os.path.join(out, f"{sync}.go"), "w").close()

        try:
            if not wait_for(r"live script: waiting for \S*/armed\.go", 400):
                c.check(s, "the client reached the toggles", False, f"drive exit {p.poll()}")
                return
            ident = identity_of(out)
            ident_box[0] = ident
            # Strikes until my scene holds fighter copies (a `fighter` row lasts until death), so
            # the first fighter step has rows to move; a refused strike also answers 200.
            for _ in range(8):
                strike()
                time.sleep(1.5)
                held = fighter_copies(ident)
                if held["public"] + held["private"] > 0:
                    break
            report_held = fighter_copies(ident)
            go("armed")
            time.sleep(4)
            quiet = gap(time.time() - 3.5, time.time())
            for law, value in steps:
                before = feed_of(state)
                state[law] = value
                after = feed_of(state)
                rev = revision()
                fighting = law == "combat_feed_on" and before != after
                if fighting:
                    strike()   # windup about 0.65 s: the blow lands across the call
                    time.sleep(0.4)
                r = set_law(law, value)
                r.update(before=before, after=after, state=dict(state))
                if fighting:
                    time.sleep(0.2)
                    strike()
                if value == "false" and law == "fighter_tables_on" and before != after:
                    gone = None
                    while time.time() - r["t1"] < 3.0:
                        if q("SELECT id FROM seen_fighter_copy") == []:
                            gone = round((time.time() - r["t1"]) * 1000, 1)
                            break
                        time.sleep(0.02)
                    r["empty_after_ms"] = gone
                time.sleep(3.0)
                r["rev_before"], r["rev_after"] = rev, revision()
                r["gap_ms"] = gap(r["t0"] - 0.5, r["t1"] + 1.5)
                r["fighters"] = fighter_copies(ident) if ident else None
                results.append(r)
            time.sleep(4.5)   # the last rows written are taken (and polled) before the reconnect
            t_reconnect = time.time()
            go("toggled")
            offline = wait_for(r"offline: ", 30)
            wait_for(r"live script: waiting for \S*/done\.go", 60)
            go("done")
            p.wait(timeout=120)
            fresh_out, fresh_code, _ = drive(run, f"{s}-fresh", "ready;wait:4;dump:fresh;quit", env={"LIVING_GAME_SEEN_LOG": os.path.join(base, f"{name}-fresh.seen.jsonl")})
        finally:
            if p.poll() is None:
                p.terminate()
            for law in DELIVERY_LAWS:
                set_law(law, original.get(law, shipped[law]))
            stop.set()
            drive_log.close()
    lines = timed_lines(out)
    frames = seen_frames(seen_path)
    report = {"identity": ident, "start": start, "quiet_gap_ms": quiet, "targets": targets, "striker": striker, "strikes": strikes, "steps": results}
    c.check(s, "fighters in my scene before the first call", report_held["public"] + report_held["private"] > 0, json.dumps(report_held))
    c.check(s, "the world's tick ran between calls (quiet gap under 150 ms)", quiet < 150, f"{quiet}")
    in_place = r"rules: law overrides laid over in place .*changed \[\"{law}\"\]; delivery true cover false gaze false"
    key = lambda k: (lambda f: {row[0] for row in f.get("rows", [])} if k == "rows" else set(f.get(k, [])))
    for r in results:
        law, value, before, after = r["law"], r["value"], tuple(r["before"]), tuple(r["after"])
        tag = f"{law}={value} ({after[0]}, motion {after[1]}, characters {after[2]}, fighters {after[3]}, combat feed {after[4]})"
        c.check(s, f"{tag}: set_world_law accepted", r["code"] == 200, r["reply"])
        c.check(s, f"{tag}: the script revision did not change", r["rev_before"] == r["rev_after"] and r["rev_before"] is not None, f"{r['rev_before']} -> {r['rev_after']}")
        c.check(s, f"{tag}: no world freeze (tick gap under 150 ms)", r["gap_ms"] < 150, f"{r['gap_ms']} ms")
        if after == before:
            eff = first_after(lines, "rules: " + " ".join(f"{k} {r['state'][k]}" for k in DELIVERY_LAWS), r["t0"] - 0.05, r["t0"] + 3.0)
            r["effect_ms"] = round((eff[0] - r["t1"]) * 1000, 1) if eff else None
            # A row rewritten with the value it had is no change in force: no line at all.
            kept = first_after(lines, r"perception: subscribing", r["t0"] - 0.05, r["t0"] + 3.0) is None
            c.check(s, f"{tag}: the set kept (no subscribe)", kept)
            continue
        hit = first_after(lines, in_place.format(law=law), r["t0"] - 0.05, r["t0"] + 3.0)
        r["laid_over_ms"] = round((hit[0] - r["t1"]) * 1000, 1) if hit else None
        c.check(s, f"{tag}: laid over in place as delivery", hit is not None)
        sub = first_after(lines, set_sub_line(after), r["t0"] - 0.05)
        eff = first_after(lines, set_on_line(after), r["t0"] - 0.05)
        r["effect_ms"] = round((eff[0] - r["t1"]) * 1000, 1) if eff else None
        r["switch_line"] = eff[1] if eff else None
        c.check(s, f"{tag}: the new set subscribed beside the old and the reads moved to it within 1.5 s", sub is not None and eff is not None and eff[0] - r["t1"] < 1.5, f"{r['effect_ms']} ms")
        c.check(s, f"{tag}: the switch line lists nobody, no character and no fighter missing", bool(eff) and eff[1].count("missing now []") == 3, eff[1] if eff else "")
        if eff:
            # From the call on: "kept" is what the last frame before the call held, so a creature
            # coming into sight just before it is not missing from the frames before that.
            t0_ms, t1_ms = r["t0"] * 1000, (eff[0] + 1.0) * 1000
            pre = [f for f in frames if f.get("wall_ms", 0) < r["t0"] * 1000]
            post = [f for f in frames if f.get("wall_ms", 0) >= t1_ms]
            window = [f for f in frames if t0_ms <= f.get("wall_ms", 0) <= t1_ms]
            counts = {}
            for k in ("rows", "characters", "fighters"):
                keep = (key(k)(pre[-1]) & key(k)(post[0])) if pre and post else set()
                counts[k] = (len(keep), len([f for f in window if keep - key(k)(f)]))
            r["frames"], r["kept"] = len(window), counts
            c.check(s, f"{tag}: no frame without a creature, a character or a fighter kept across the switch",
                    window and all(counts[k][0] > 0 and counts[k][1] == 0 for k in counts), f"{len(window)} frames; kept, frames missing one: {json.dumps(counts)}")
            tables = post[0].get("tables", {}) if post else {}
            c.check(s, f"{tag}: the reads take the tables the laws name", post and post[0].get("reads") == after[0] and reads_match(tables, after), json.dumps(tables))
        cp = r["fighters"] or {}
        if law == "fighter_tables_on":
            if value == "true":
                c.check(s, f"{tag}: my fighter copies all in seen_fighter_copy, none left private", cp.get("public", 0) > 0 and cp.get("private") == 0, json.dumps(cp))
            else:
                c.check(s, f"{tag}: the kill switch: seen_fighter_copy empty within a second, my copies back in the private tables",
                        r.get("empty_after_ms") is not None and r["empty_after_ms"] < 1000 and cp.get("public_all") == 0 and cp.get("private", 0) > 0, f"empty after {r.get('empty_after_ms')} ms; {json.dumps(cp)}")
    combos = sorted({(r["after"][0], r["after"][3], r["after"][4]) for r in results} | {(feed_of(start)[0], *feed_of(start)[3:])})
    report["combinations"] = combos
    c.check(s, "fighter table and combat feed in all four combinations in both frame-tier states", len(combos) == 8, json.dumps(combos))
    copies = sorted({(r["after"][1], r["after"][2], r["after"][3], r["after"][4]) for r in results})
    report["with_copy_tables"] = copies
    c.check(s, "both new laws on with the copy tables off and on", (False, False, True, True) in copies and (True, True, True, True) in copies, json.dumps(copies))
    # No event missing: every combat_seen row the authority wrote for me while the client ran, in
    # the frames' wall time, was taken by the client, whichever source was in place.
    taken = {}
    for f in frames:
        for i in f.get("combat", []):
            taken.setdefault(int(i), f)
    t_first = (frames[0]["wall_ms"] / 1000) if frames else 0
    t_last = (frames[-1]["wall_ms"] / 1000 - 1.0) if frames else 0
    polled = {i: r for i, r in feed_rows.items() if t_first <= r["first"] <= t_last}
    missing = sorted(set(polled) - set(taken))
    by_source = {}
    for i in polled:
        f = taken.get(i)
        if f:
            k = "combat_feed" if f.get("tables", {}).get("combat_feed") else "my_combat"
            by_source[k] = by_source.get(k, 0) + 1
    switch_windows = [(r["t0"] - 1.0, r["t1"] + 3.0) for r in results if r["law"] == "combat_feed_on" and tuple(r["before"]) != tuple(r["after"])]
    across = sorted(i for i, r in polled.items() if any(a <= r["first"] <= b for a, b in switch_windows))
    report["events"] = {"polled": len(polled), "taken": len(taken), "missing": missing, "by_source": by_source, "across_switches": len(across),
                        "strikes": len(strikes), "strikes_ok": sum(1 for x in strikes if x["code"] == 200), "skipped": sum(1 for x in strikes if x["code"] is None)}
    c.check(s, "every combat_seen row the authority wrote for me was taken by the client, whichever source",
            polled and not missing and by_source.get("combat_feed", 0) > 0 and by_source.get("my_combat", 0) > 0, json.dumps(report["events"]))
    c.check(s, "events in flight across the combat-feed switches, none missing", len(across) >= len(switch_windows) and not (set(across) & set(missing)), f"{len(across)} rows across {len(switch_windows)} switches")
    final = feed_of({**start, **{r["law"]: r["value"] for r in results}})
    after_rc = [(t, x) for t, x in lines if t >= t_reconnect]
    subscribed = [x for _, x in after_rc if x.startswith("perception: subscribing")]
    report["reconnect"] = {"offline": bool(offline), "subscribed": subscribed}
    c.check(s, "reconnect with both new laws on: the client went offline and came back", bool(offline) and any(x.startswith("world subscribed after") for _, x in after_rc))
    c.check(s, "reconnect: the first set chosen reads the fighter table and the combat feed, no view set before it",
            bool(subscribed) and re.search(set_sub_line(final), subscribed[0]) is not None and all("fighters true combat_feed true" in x for x in subscribed), f"{subscribed}")
    c.check(s, "reconnect: my_combat read once, and the reads moved to the set", any(x.startswith("combat feed: my_combat read once") for _, x in after_rc) and first_after(lines, set_on_line(final), t_reconnect) is not None)
    flog = log(fresh_out) if fresh_out else ""
    fsub = re.findall(r"perception: subscribing the .*", flog)
    report["fresh"] = {"exit": fresh_code, "subscribed": fsub}
    c.check(s, "fresh client with both new laws on: only that set subscribed and read, my_combat read once",
            len(fsub) == 1 and re.search(set_sub_line(final), fsub[0]) is not None and re.search(set_on_line(final), flog) is not None and "combat feed: my_combat read once" in flog, f"{fsub}")
    alive = {i: (q(f"SELECT alive FROM character WHERE id = {i}") or [{}])[0].get("alive") for i in targets}
    c.check(s, "the struck residents are alive (and put back by the fixture)", all(v is True for v in alive.values()), json.dumps({i: [alive[i], hp(i)] for i in targets}))
    c.check(s, "the six delivery laws restored to the world's own values", {k: own_laws(lambda x: sql(run, x)).get(k, shipped[k]) for k in DELIVERY_LAWS} == {k: original.get(k, shipped[k]) for k in DELIVERY_LAWS})
    json.dump(report, open(os.path.join(base, f"{name}.json"), "w"), indent=1)


# The least health a resident may have to be struck by `combat-switches` (of 100).
STRIKE_FLOOR = 50.0


def death_truth(rows, me):
    """My death as the authority's rows give it (owner SQL on `combat_seen`, kept two minutes,
    snapshot by the drive while dead, before anything else can clear it): the killer (the death
    row's target) and the witnesses' ids (id 0 is no one)."""
    deaths = [r for r in rows if r["kind"] == 7 and r["actor"] == me]
    if not deaths:
        return None
    d = max(deaths, key=lambda r: r["id"])
    return {"death_id": d["id"], "killer": d["target"] or None, "witnesses": sorted({r["actor"] for r in rows if r["kind"] == 8 and r["actor"] != 0 and r["id"] > d["id"]})}


@scenario("combat-switches-death", explicit=True)
def combat_switches_death(run, c):
    """The death screen is the same whichever source the combat feed comes from (dev-box's
    death-screen equality, docs/BATTLE_VIEWERS.md addendum 4, on the client): two fresh players
    killed by a stranger (verify.py's player identity, the death scenario's sharper free strike),
    beside a resident held still as a witness, one with `combat_feed_on` off (the `my_combat`
    view) and one with it on (the `combat_feed` event table). In each, the death screen (cause,
    killer, witnesses: the dump's `death`) equals what the authority's `combat_seen` rows say;
    stays the same when the law flips while dead and back, and across a reconnect while dead (the
    connection's first set then reads `my_combat` once with the law on); and was taken from the
    arm's source (the seen log). Across the two arms: the same cause words, the same killer, the
    same names for the witnesses both had. The laws and the resident are put back."""
    s = "combat-switches-death"
    original = own_laws(lambda x: sql(run, x))
    shipped = {k: shipped_law(k) for k in DELIVERY_LAWS}
    num = lambda k, d: original.get(k) or (re.search(rf"\b{k}:\s*([0-9.]+)", open(os.path.join(ROOT, "living/scripts/skills.rhai")).read()) or [None, d])[1]
    dmg0, cost0 = num("dmg_strike", "5"), num("cost_strike", "20")
    w = (residents(run, 1) or [None])[0]
    striker = second_player(run, "Striker")
    c.check(s, "a resident to witness and a stranger to strike", w is not None and striker is not None, f"{w} {striker}")
    if w is None or striker is None:
        return
    d = os.path.join(ROOT, ".local/living/verify", run, "ui")
    os.makedirs(d, exist_ok=True)
    arms = {}
    hits = "".join(f"sync:hit{i};wait:0.9;" for i in range(8))
    try:
        with resident_fixture(run, [w]):
            for arm in ("off", "on"):
                law = "true" if arm == "on" else "false"
                flip = "false" if arm == "on" else "true"
                call_admin(run, "set_world_law", ["combat_feed_on", law], check=True)
                name = f"{s}-{arm}"
                seen = os.path.join(d, f"{name}.seen.jsonl")
                plan = ("ready;wait:3;sync:scene;sync:sharp;sync:near;wait:1.5;dump:00;" + hits +
                        "wait:2.5;shot:01_died;dump:01;sync:truth;sync:flip;wait:2.5;dump:02;sync:back;wait:2.5;dump:03;reconnect;wait:8;shot:04_reconnected;dump:04;sync:blunt;quit")
                syncs = ['sharp=set_world_law|"dmg_strike"|"40";set_world_law|"cost_strike"|"0"', f"near=place_at|{striker}|(mx+0.9)|(my)",
                         *[f'hit{i}=player|use_skill|strike|{{me}}|(mx)|(my)' for i in range(8)],
                         "truth=sql|SELECT id, kind, actor, target FROM combat_seen WHERE viewer = 0x{ident}",
                         f'flip=set_world_law|"combat_feed_on"|"{flip}"', f'back=set_world_law|"combat_feed_on"|"{law}"',
                         f'blunt=set_world_law|"dmg_strike"|"{dmg0}";set_world_law|"cost_strike"|"{cost0}"']
                tok = os.path.join(d, f"{name}-{int(time.time())}.token")
                out, code, text = drive(run, name, plan, places=[f"{w}:-1.4:1.0"], syncs=syncs, extra=["--token", tok, "--player", f"Fallen {arm}"], env={"LIVING_GAME_SEEN_LOG": seen})
                scene = json.load(open(os.path.join(out, "scene.json"))) if os.path.exists(os.path.join(out, "scene.json")) else {}
                me, ident = scene.get("me"), identity_of(out)
                snap = ((scene.get("snaps") or {}).get("truth") or [{}])[0].get("rows")
                truth = death_truth(snap, me) if snap is not None and me else None
                dumps = {k: (dump(out, k) or {}).get("death") for k in ("01", "02", "03", "04")}
                frames = seen_frames(seen)
                death_frame = next((f for f in frames if truth and truth["death_id"] in f.get("combat", [])), None)
                text_log = log(out)
                arms[arm] = {"me": me, "identity": ident, "truth": truth, "dumps": dumps, "exit": code,
                             "death_taken_from": None if not death_frame else ("combat_feed" if death_frame.get("tables", {}).get("combat_feed") else "my_combat"),
                             "read_once": re.findall(r"combat feed: my_combat read once \((\d+) rows\)", text_log)}
                a = arms[arm]
                c.check(s, f"{arm}: the client ran, joined and was killed by the stranger", code == 0 and truth is not None and truth["killer"] == striker, json.dumps(truth))
                first = dumps["01"]
                c.check(s, f"{arm}: the death screen shows the authority's killer and witnesses",
                        bool(first) and first.get("killer_id") == (truth or {}).get("killer") and sorted(first.get("witness_ids") or []) == (truth or {}).get("witnesses")
                        and (first.get("cause") or "").startswith("Killed by") and w in (first.get("witness_ids") or []), json.dumps({"screen": first, "truth": truth}))
                c.check(s, f"{arm}: the same screen after the law flipped while dead, back, and across a reconnect while dead",
                        bool(first) and all(dumps[k] == first for k in ("02", "03", "04")), json.dumps(dumps))
                c.check(s, f"{arm}: the death was taken from the arm's source ({'combat_feed' if arm == 'on' else 'my_combat'})",
                        a["death_taken_from"] == ("combat_feed" if arm == "on" else "my_combat"), str(a["death_taken_from"]))
                if arm == "on":
                    c.check(s, "on: the reconnect while dead read my_combat once, with the death's rows", bool(a["read_once"]) and int(a["read_once"][-1]) >= 1 + len((truth or {}).get("witnesses", [])), str(a["read_once"]))
    finally:
        call_admin(run, "set_world_law", ["dmg_strike", dmg0])
        call_admin(run, "set_world_law", ["cost_strike", cost0])
        call_admin(run, "set_world_law", ["combat_feed_on", original.get("combat_feed_on", shipped["combat_feed_on"])])
    off, on = (arms.get(k, {}).get("dumps", {}).get("01") or {} for k in ("off", "on"))
    names = lambda x: dict(zip(x.get("witness_ids") or [], x.get("witnesses") or []))
    common = set(names(off)) & set(names(on))
    c.check(s, "off against on: the same cause words, killer and witnesses' names",
            bool(off) and bool(on) and off.get("cause") == on.get("cause") and off.get("killer_id") == on.get("killer_id") and common >= {w, striker} - {None} and all(names(off)[i] == names(on)[i] for i in common),
            json.dumps({"off": off, "on": on}))
    c.check(s, "combat_feed_on restored to the world's own value", own_laws(lambda x: sql(run, x)).get("combat_feed_on", shipped["combat_feed_on"]) == original.get("combat_feed_on", shipped["combat_feed_on"]))
    json.dump(arms, open(os.path.join(d, f"{s}.json"), "w"), indent=1)


@scenario("combat-switches-ui", explicit=True)
def combat_switches_ui(run, c):
    """camera, talk, far and the combat scenarios (death, bar, own, committed, move-off) with
    `fighter_tables_on` and `combat_feed_on` both on: each scenario's own checks, and every client
    those scenarios started read the fighter table and the combat feed (its switch lines name
    them, and no other set was read). The two laws are put back after."""
    s = "combat-switches-ui"
    original = own_laws(lambda x: sql(run, x))
    shipped = {k: shipped_law(k) for k in DELIVERY_LAWS}
    t0 = time.time()
    try:
        for law in COMBAT_LAWS:
            call_admin(run, "set_world_law", [law, "true"], check=True)
        laws = own_laws(lambda x: sql(run, x))
        c.check(s, "both laws read on in law_override", all(laws.get(k) == "true" for k in COMBAT_LAWS), json.dumps({k: laws.get(k) for k in DELIVERY_LAWS}))
        for name in ("camera", "talk", "far", "death", "bar", "own", "committed", "move-off"):
            SCENARIOS[name](run, c)
        laws = own_laws(lambda x: sql(run, x))
        c.check(s, "both laws still on after the scenarios (their installs kept them)", all(laws.get(k) == "true" for k in COMBAT_LAWS), json.dumps({k: laws.get(k) for k in DELIVERY_LAWS}))
    finally:
        for law in COMBAT_LAWS:
            call_admin(run, "set_world_law", [law, original.get(law, shipped[law])], check=True)
    logs = [p for p in glob.glob(os.path.join(ROOT, ".local/living/verify", run, "ui", "*", "client.log")) if os.path.getmtime(p) >= t0]
    on = []
    for p in sorted(logs):
        t = log(os.path.dirname(p))
        if "playing character" not in t:
            continue
        reads = re.findall(r"perception: on the \w+ set after \d+ ms \(tables: motion \w+ characters \w+ fighters (\w+) combat_feed (\w+)\b", t)
        on.append((os.path.basename(os.path.dirname(p)), reads))
    bad = [(n, r) for n, r in on if not r or any(x != ("true", "true") for x in r)]
    c.check(s, f"every client of the scenarios read the fighter table and the combat feed ({len(on)} clients)", on and not bad, json.dumps(bad or [n for n, _ in on]))
    json.dump({"clients": on}, open(os.path.join(ROOT, ".local/living/verify", run, "ui", f"{s}.json"), "w"), indent=1)


@scenario("combat-switches-cost", explicit=True)
def combat_switches_cost(run, c):
    """kB/s and near p90 with each of `fighter_tables_on` and `combat_feed_on` on against off
    (docs/BATTLE_VIEWERS.md, "Rollout"), as `battle-views-cost` measures them (two places, four
    drives each, a byte-counting relay, the walker 1.2 m away), the walker also jumping every
    third move so the fighter copies and the combat feed carry rows. Each law alone; the other
    stays as the world has it. `combat-switches-cost.json`."""
    s = "combat-switches-cost"
    report = {}
    for law in COMBAT_LAWS:
        report[law] = delivery_cost(run, c, s, (law,), f"{s}-{law}", fight=True)
    json.dump(report, open(os.path.join(ROOT, ".local/living/verify", run, "ui", f"{s}.json"), "w"), indent=1)


@scenario("gaze", cullet=True, explicit=True)
def gaze(run, c):
    """Drive zoom through all gaze bands, coalescing, reconnect and the Cullet hedge."""
    name = "gaze"
    state = {"gaze_on": "false", "fov_on": "true", "cover_sight_on": "false", "cover_brush_on": "true"}
    ids = residents(run, 5)
    if len(ids) != 5:
        c.check(name, "five stationary residents available", False, repr(ids))
        return
    near, far, flank, rear, middle = ids
    open_eye = (781.5, 457.5)
    hedge_eye, hedge_contact = (523.5, 698.5), (527.5, 698.5)
    open_targets = {near: (783.5, 457.5), far: (837.5, 457.5), flank: (781.5, 469.5), rear: (769.5, 457.5), middle: (821.5, 457.5)}
    hedge_targets = {near: hedge_contact, flank: (523.5, 697.5)}
    stops = (("far", 1, -30, 19.0), ("middle", 0, 11, 12.0), ("near", 2, 30, 8.0))

    def setup(eye, points):
        return ";".join([f"place_at|{{me}}|{eye[0]}|{eye[1]}"] +
                        [f"place_at|{id}|{x}|{y};set_behavior|{id}|{json.dumps(json.dumps({'wait': 600}))}"
                         for id, (x, y) in points.items()])

    def snapshot(label):
        return (f"{label}=client_sql|SELECT * FROM my_senses_v_2;"
                "client_sql|SELECT * FROM my_senses;"
                "client_sql|SELECT id FROM seen_characters;"
                f"sql|SELECT id,x,y FROM body WHERE id = {{me}} OR id = {near} OR id = {far} OR id = {flank} OR id = {rear} OR id = {middle};"
                "sql|SELECT * FROM cover_law;sql|SELECT * FROM attention WHERE id = {me}")

    directory = os.path.join(ROOT, ".local/living/verify", run, "ui", f"{name}-{THEME}" if THEME else name, "fields")
    for path in glob.glob(os.path.join(directory, "field-*")):
        os.remove(path)
    syncs = [
        "daylight=sql|UPDATE world SET epoch_ms = {epoch_at:12} WHERE id = 0",
        f"open={setup(open_eye, open_targets)}",
        f"hedge={setup(hedge_eye, hedge_targets)}",
        'enable=set_world_law|"gaze_on"|"true"',
        'cover_on=set_world_law|"cover_sight_on"|"true"',
        'disable=set_world_law|"gaze_on"|"false"',
    ]
    plan = ["ready", "frame:0", "sightlook:shade", "sync:daylight", "sync:open",
            "look:270", "wait:0.8", "look:90", "cursor:0.7,0.55", "wait:2"]
    labels = ["off_before"]
    plan += ["sync:off_before", "shot:off_before", "sync:enable"]
    for fixture in ("open", "hedge"):
        if fixture == "hedge":
            plan += ["sync:cover_on", "sync:hedge", "wait:2"]
        for stop, _, notches, _ in stops:
            label = f"{fixture}_{stop}"
            labels.append(label)
            plan += [f"notches:{notches}", "wait:1.6"]
            if fixture == "hedge":
                plan += [f"pointat:{hedge_contact[0]},{hedge_contact[1]}:1", "wait:0.3"]
            plan += [f"sync:{label}", f"dump:{label}", f"shot:{label}", "cursor:0.7,0.55"]
        if fixture == "open":
            labels += ["spin_start", "spin_end", "after_reconnect"]
            plan += ["notches:-30", "wait:1.6", "sync:spin_start",
                     "notches:30", "wait:0.1", "notches:-30", "wait:0.1", "notches:30",
                     "wait:0.1", "notches:-30", "wait:0.1", "notches:30", "wait:0.1",
                     "notches:-30", "wait:1.5", "sync:spin_end",
                     "reconnect", "wait:0.35", "notches:30", "wait:6", "sync:after_reconnect"]
    labels.append("off_after")
    plan += ["sync:disable", "notches:-30", "wait:0.5", "notches:11", "wait:3.5", "sync:off_after", "shot:off_after", "quit"]
    with sight_fixture(run, CULLET_SIGHT), resident_fixture(run, ids):
        for law, value in state.items():
            call_admin(run, "set_world_law", [law, value], check=True)
        out, code, drive_log = drive(run, name, ";".join(plan), syncs=syncs + [snapshot(k) for k in labels],
                                     env={"LIVING_GAME_CONTROL": "cursor", "LIVING_SIGHT_FIELD_DUMP": directory,
                                          "RUST_LOG": "info,wgpu=warn,naga=warn,living_game::net=debug,living_game::sightedge=trace"})

    scene = dump(out, "scene") or {}
    me, snaps = scene.get("me"), scene.get("snaps", {})
    trace = log(out)
    fields = field_dumps(directory) if os.path.isdir(directory) else []
    proof = {}
    sense_keys = ("id", "sight", "hearing", "field", "focal_deg", "side_deg", "side_share", "near_m", "margin_deg", "at_ms")
    sent = lambda text: [int(b) for b in re.findall(r"gaze sent band=(\d+)", text)]

    def sample(label, eye, band, points):
        rows = snaps.get(label, [])
        if len(rows) != 6:
            return {"ok": False, "missing": label}
        projected, legacy, perceived, positions, cover, intent = [r["rows"] for r in rows]
        view_row = projected[0] if len(projected) == 1 else {}
        senses = view_row.get("senses", {})
        if isinstance(senses, list):
            senses = dict(zip(sense_keys, senses))
        candidates = [(meta, pixels) for meta, pixels in fields
                      if meta["band"] == band and meta["wall_ms"] <= rows[0]["wall_ms"]
                      and math.dist(meta["eye"], eye) < 0.2]
        meta, pixels = candidates[-1] if candidates else ({}, b"")
        visible = {r["id"] for r in perceived}
        position_by_id = {r["id"]: (r["x"], r["y"]) for r in positions}
        probes = {}
        for id, point in points.items():
            shade = texel(meta, pixels, *point) if meta else None
            probes[id] = {"point": point, "exact": position_by_id.get(id) == point, "texel": shade,
                          "authority": id in visible,
                          "shade": shade is not None and shade >= 128 and math.dist(eye, point) <= meta["radius"]}
        d = dump(out, label) or {}
        matching = bool(meta.get("facing") and senses) and all(
            abs(meta["facing"][k] - senses[k]) < 0.004 for k in ("sight", *sense_keys[4:-1]))
        matching = matching and abs(meta["radius"] - senses["sight"]) < 0.004
        ok = (view_row.get("id") == me and view_row.get("band") == band
              and bool(intent) and intent[0]["band"] == band and matching and position_by_id.get(me) == eye
              and all(p["exact"] and p["texel"] is not None and p["shade"] == p["authority"] for p in probes.values())
              and any(p["authority"] for p in probes.values()) and not all(p["authority"] for p in probes.values())
              and (d.get("extra") or {}).get("sight_look") == "shade"
              and os.path.isfile(os.path.join(out, f"{label}.png")))
        return dict(ok=ok, view=view_row, senses=senses, legacy=legacy, field=meta, probes=probes, cover=cover,
                    drawn=near in {row["id"] for row in d.get("looks") or []},
                    seen=near in {row["id"] for row in d.get("seen") or []},
                    hovered=near in {row["id"] for row in d.get("hovered") or []},
                    picked=d.get("under") == near, height=view(d).get("height", -1), pitch=view(d).get("pitch", -1))

    def stops_at(fixture, eye, points):
        result = {stop: sample(f"{fixture}_{stop}", eye, band, points) for stop, band, _, _ in stops}
        good = all(result[stop]["ok"] and abs(result[stop]["height"] - height) < 0.1
                   and abs(result[stop]["pitch"] - 58) < 0.1 for stop, _, _, height in stops)
        return result, good

    opened, opened_ok = stops_at("open", open_eye, open_targets)
    senses_at_stops = [opened[stop].get("senses", {}) for stop, *_ in stops]
    ranges = [r.get("sight", 0) for r in senses_at_stops]
    angles = [(r.get("focal_deg"), r.get("side_deg")) for r in senses_at_stops]
    probe_ids = (near, middle, far, flank, rear)
    sampled_fields = [[row.get("probes", {}).get(id, {}).get("authority") for id in probe_ids]
                      for row in opened.values()]
    distinct = sampled_fields == [[True, True, True, False, False],
                                  [True, True, False, True, False],
                                  [True, False, False, True, False]]
    legacy = ((snaps.get("off_before") or [{}, {}])[1].get("rows") or [{}])[0]
    same_middle = bool(legacy and senses_at_stops[1]) and all(legacy[k] == senses_at_stops[1][k] for k in sense_keys[1:-1])
    frame_pattern = r"gaze shade confirmed=(-?\d+) drawn=(-?\d+) radius=([-\d.]+) revision=(\d+) mode=(\d+)"
    off_before, _, enabled = partition_sync(trace, "enable")
    off_after = partition_sync(trace, "disable", last=True)[2]

    def legacy_shade(label, output, eye):
        rows = snaps.get(label, [])
        frames = re.findall(frame_pattern, output)
        if len(rows) != 6 or rows[0]["rows"] or len(rows[1]["rows"]) != 1 or not frames:
            return False
        row = rows[1]["rows"][0]
        confirmed, drawn, radius, revision, mode = frames[-1]
        return (not sent(output) and "gaze refused" not in output and confirmed == drawn == "-1"
                and int(revision) > 0 and mode == "1" and abs(float(radius) - row["sight"]) < 0.004
                and any(meta["band"] is None and meta["facing"]
                        and math.dist(meta["eye"], eye) < 0.2 and abs(meta["sight"] - row["sight"]) < 0.004
                        for meta, _ in fields))

    off_ok = legacy_shade("off_before", off_before, open_eye) and legacy_shade("off_after", off_after, hedge_eye)
    approach = partition_sync(enabled.partition("live script: notches:-30")[2], "spin_start")[0]
    proof["stops"] = dict(samples=opened, reach=ranges, angles=angles, middle_matches_legacy=same_middle,
                          off_legacy=off_ok, sampled_fields=sampled_fields, sends=sent(approach))
    c.check(name, "1. Three fixed camera stops have different authority-matched Shade fields",
            code == 0 and opened_ok and distinct and ranges[0] > ranges[1] > ranges[2] and same_middle and off_ok
            and angles == [(35, 65), (70, 110), (110, 155)] and sent(approach)[:3] == [1, 0, 2],
            repr((ranges, angles, sampled_fields, opened_ok, same_middle, off_ok, drive_log[-300:])))

    spin = partition_sync(partition_sync(trace, "spin_start")[2], "spin_end")[0]
    replies = [(int(b), int(t)) for b, t in re.findall(r"gaze accepted band=(\d+) at_us=(\d+)", spin)]
    interval_ok = len(replies) >= 2 and all(b[1] - a[1] >= 250_000 for a, b in zip(replies, replies[1:]))
    frames = [(int(cb), int(db), float(r), int(rev), int(mode)) for cb, db, r, rev, mode in re.findall(frame_pattern, spin)]
    rendered = [b for i, (_, b, _, _, _) in enumerate(frames) if i == 0 or b != frames[i - 1][1]]
    confirmed = [b for i, (b, _, _, _, _) in enumerate(frames) if i == 0 or b != frames[i - 1][0]]
    same_frame = all(
        (a[3] == b[3] if a[1] == b[1] else b[0] == b[1] and a[3] != b[3])
        for a, b in zip(frames, frames[1:])
    )
    radius_by_band = {band: r for (_, band, _, _), r in zip(stops, ranges)}
    no_flicker = bool(frames) and rendered == confirmed and same_frame and all(
        mode == 1 and abs(radius - radius_by_band.get(b, -1)) < 0.004 for _, b, radius, _, mode in frames)
    zoom_times = re.findall(r"(\d\d:\d\d:\d\d(?:\.\d+)?)Z.*live script: notches:", spin)
    seconds = lambda t: sum(float(x) * (60 ** i) for i, x in enumerate(reversed(t.split(":"))))
    duration = seconds(zoom_times[-1]) - seconds(zoom_times[0]) if len(zoom_times) == 6 else None
    final = (snaps.get("spin_end") or [{}])[0].get("rows") or [{}]
    max_per_second = max((sum(0 <= b[1] - a[1] < 1_000_000 for b in replies) for a in replies), default=0)
    proof["spin"] = dict(duration_s=duration, accepted=replies, max_per_second=max_per_second,
                         frames=frames, rendered=rendered,
                         confirmed=confirmed, no_flicker=no_flicker)
    c.check(name, "2. Rapid wheel spin respects the limiter, keeps the last band, and does not flicker",
            duration is not None and 0 < duration < 1 and interval_ok and max_per_second <= 4 and no_flicker
            and replies[-1][0] == final[0].get("band") == 1,
            repr((duration, replies, len(frames), rendered, confirmed, no_flicker)))

    reconnect = partition_sync(trace.partition("live script: reconnect")[2], "after_reconnect")[0]
    events = re.findall(r"(?m)(offline:.*|connected as .*|world subscribed .*|gaze owner applied band=\d+[^\n]*|gaze sent band=\d+)", reconnect)
    recovered = (snaps.get("after_reconnect") or [{}])[0].get("rows") or [{}]
    order = [re.sub(r"^(gaze (?:owner applied|sent) band=\d+).*", r"\1", line) for line in events if line.startswith("gaze ")]
    proof["reconnect"] = dict(events=events, after=recovered)
    zoom_at = reconnect.find("live script: notches:30")
    subscribed_at = reconnect.find("world subscribed")
    c.check(name, "3. Reconnect restores Far before sending the queued Near band",
            "offline:" in reconnect and 0 <= zoom_at < subscribed_at
            and order == ["gaze owner applied band=1", "gaze sent band=2", "gaze owner applied band=2"]
            and recovered[0].get("band") == 2, repr(events))

    hedge, hedge_ok = stops_at("hedge", hedge_eye, hedge_targets)
    hidden = all(row.get("cover") and row["cover"][0]["cover_sight_on"] and row["cover"][0]["cover_brush_on"]
                 and row["probes"][near]["texel"] == 0 and not row["probes"][near]["authority"]
                 and not any(row[k] for k in ("seen", "drawn", "hovered", "picked")) for row in hedge.values())
    proof["hedge"] = hedge
    c.check(name, "4. Gaze and cover hide the Cullet hedge contact at every stop", hedge_ok and hidden,
            repr({stop: (row["ok"], row.get("probes")) for stop, row in hedge.items()}))
    with open(os.path.join(out, "gaze-proof.json"), "w") as f:
        json.dump(proof, f, indent=1)


@scenario("cover", cullet=True)
def cover(run, c):
    """The same Cullet sight rays with cover on and off, through the real client."""
    ids = residents(run, 1)
    if not ids:
        c.check("cover", "adult resident available", False)
        return
    with sight_fixture(run, CULLET_SIGHT), resident_fixture(run, ids):
        for law, value in (("gaze_on", "false"), ("fov_on", "false"), ("cover_brush_on", "true")):
            call_admin(run, "set_world_law", [law, value], check=True)
        for fixture, eye, contact, blocks in (
            ("trunk", (781.5, 457.5), (785.5, 457.5), True),
            ("edge", (781.5, 457.5), (785.5, 459.5), False),
            # The closer point still crosses the brush and stays in the near camera's frame.
            ("brush", (608.5, 479.5), (608.5, 474.5), True),
            # Cullet's mid_row_plot_toft_3_hedge, 1.8 m high, plan origin (510, 784).
            ("hedge", (523.5, 698.5), (527.5, 698.5), True),
        ):
            cover_pair(run, c, ids[0], fixture, eye, contact, blocks)
        cover_canopy(run, c)


def cover_pair(run, c, target, fixture, eye, contact, blocks):
    stops = (("far", -30, 19.0), ("middle", 11, 12.0), ("near", 30, 8.0))
    name = f"cover-{fixture}"
    directory = os.path.join(ROOT, ".local/living/verify", run, "ui",
                             f"{name}-{THEME}" if THEME else name, "fields")
    if os.path.isdir(directory):
        for filename in os.listdir(directory):
            if re.fullmatch(r"field-\d+\.(json|pgm)", filename):
                os.remove(os.path.join(directory, filename))
    x, y = contact
    syncs = [
        "daylight=sql|UPDATE world SET epoch_ms = {epoch_at:12} WHERE id = 0",
        'enable=set_world_law|"cover_sight_on"|"true"',
        'disable=set_world_law|"cover_sight_on"|"false"',
        f"positions=place_at|{{me}}|{eye[0]}|{eye[1]};place_at|{target}|{x}|{y};"
        f"set_behavior|{target}|{json.dumps(json.dumps({'wait': 600}))}",
    ]
    plan = ["ready", "weapon:sheathe", "frame:0", "yaw:0", "sightlook:shade", "sync:daylight", "sync:positions"]
    for state in ("on", "off"):
        plan += [f"sync:{'enable' if state == 'on' else 'disable'}", "wait:7"]
        for stop, notches, _ in stops:
            key = f"{state}_{stop}"
            syncs.append(f"{key}=sql|SELECT body FROM perceived WHERE viewer = 0x{{ident}};"
                         "sql|SELECT * FROM cover_law;"
                         f"sql|SELECT id,x,y FROM body WHERE id = {{me}} OR id = {target}")
            plan += ["cursor:0.7,0.55", f"notches:{notches}", "wait:1.5",
                     f"pointat:{x},{y}:1.0", "wait:0.5", f"sync:{key}", f"dump:{key}", f"shot:{key}"]
            if blocks and state == "on":
                plan += ["weapon:sheathe", "wait:0.5", "tap", "wait:0.6", f"dump:{key}_talk",
                         "weapon:draw", "wait:0.5", "tap", "wait:0.6", f"dump:{key}_attack",
                         "weapon:sheathe"]
    out, code, output = drive(run, name, ";".join(plan + ["quit"]), syncs=syncs,
                              env={"LIVING_SIGHT_FIELD_DUMP": directory})
    c.check(name, "client joined and finished", code == 0, output[-500:])
    scene = dump(out, "scene") or {}
    me = scene.get("me")
    fields = field_dumps(directory) if os.path.isdir(directory) else []
    trace = log(out)
    for state in ("on", "off"):
        hidden = state == "on" and blocks
        for stop, _, height in stops:
            key = f"{state}_{stop}"
            d = dump(out, key) or {}
            talk = dump(out, f"{key}_talk") or {}
            extra = d.get("extra") or {}
            snapshots = scene.get("snaps", {}).get(key, [])
            if len(snapshots) != 3:
                c.check(name, f"{key}: authority snapshots present", False)
                continue
            perception, law, positions = [snap["rows"] for snap in snapshots]
            actual = {row["id"]: (row["x"], row["y"]) for row in positions}
            law_ok = bool(law) and law[0]["cover_brush_on"] and law[0]["cover_sight_on"] == (state == "on")
            c.check(name, f"{key}: policy and exact positions", law_ok and actual == {me: eye, target: contact}, repr(actual))
            v = view(d)
            c.check(name, f"{key}: camera stop and still", v.get("mode") == "top-down"
                    and abs(v.get("height", -1) - height) < 0.1
                    and os.path.isfile(os.path.join(out, f"{key}.png")), repr(v))
            authority = target in {row["body"] for row in perception}
            perceived = target in (d.get("perceived") or [])
            seen = target in {row["id"] for row in d.get("seen") or []}
            drawn = target in {row["id"] for row in d.get("looks") or []}
            c.check(name, f"{key}: authority and client agree on visibility",
                    (authority, perceived, seen, drawn) == (not hidden,) * 4,
                    repr((authority, perceived, seen, drawn)))
            candidates = [(meta, pixels) for meta, pixels in fields
                          if meta["wall_ms"] <= snapshots[0]["wall_ms"]
                          and math.dist(meta["eye"], eye) < 0.2]
            shade = texel(*candidates[-1], *contact) if candidates else None
            c.check(name, f"{key}: Shade agrees with authority at the target",
                    shade == (255 if authority else 0) and extra.get("sight_look") == "shade", repr(shade))
            pointer = extra.get("cursor") or {}
            on_screen = all(0 < pointer.get(axis, -1) < 1 for axis in ("fx", "fy"))
            hovered = target in {row["id"] for row in d.get("hovered") or []}
            addressed = (talk.get("typing") or {}).get("to")
            if hidden:
                segment = partition_sync(trace, key)[2].partition(f"live script: dump:{key}_attack")[0]
                strikes = re.findall(r"tap: strike \(at (.*?), weapon drawn\)", segment)
                naming = [word for kind, word in d.get("naming") or [] if kind in ("hover", "target")]
                quiet = (d.get("under") is None and not hovered and not naming
                         and d.get("targeted") is None and addressed != target
                         and bool(strikes) and all(who != f"Some({target})" for who in strikes))
                c.check(name, f"{key}: no hover, label, plate, talk or strike target",
                        on_screen and quiet, repr((pointer, d.get("under"), naming, addressed, strikes)))
            else:
                c.check(name, f"{key}: cursor can pick the visible resident",
                        on_screen and d.get("under") == target and hovered,
                        repr((pointer, d.get("under"), hovered)))


def cover_canopy(run, c):
    # Cullet's streamed land client uses the authored Hanger tree at (783.2, 457.4).
    canopy = (783.5, 457.5)
    plan = ["ready", "weapon:sheathe", "frame:0", "sync:daylight"]
    syncs = ["daylight=sql|UPDATE world SET epoch_ms = {epoch_at:12} WHERE id = 0",
             'enable=set_world_law|"cover_sight_on"|"true"',
             'disable=set_world_law|"cover_sight_on"|"false"']
    for state in ("on", "off"):
        plan += [f"sync:{'enable' if state == 'on' else 'disable'}", "wait:3"]
        for stop, notches in (("middle", -9 if state == "off" else 0), ("near", 30)):
            key = f"{state}_{stop}"
            syncs += [f"clear_{key}=place_at|{{me}}|775.5|457.5",
                      f"tree_{key}=place_at|{{me}}|{canopy[0]}|{canopy[1]}"]
            plan += [f"sync:clear_{key}", "wait:3", "cursor:0.7,0.55", f"notches:{notches}",
                     f"sync:tree_{key}", "wait:3", f"dump:{key}", f"shot:{key}"]
    name = "cover-canopy"
    out, code, output = drive(run, name, ";".join(plan + ["quit"]), syncs=syncs,
                              env={"RUST_LOG": "info,wgpu=warn,naga=warn,living_game::envs=debug"})
    c.check(name, "client joined and finished", code == 0, output[-500:])
    trace = log(out)
    for state in ("on", "off"):
        for stop, height in (("middle", 12.0), ("near", 8.0)):
            key = f"{state}_{stop}"
            d = dump(out, key) or {}
            body = (d.get("me_at") or {}).get("body") or {}
            segment = partition_sync(trace, f"tree_{key}")[2].partition(f"live script: dump:{key}")[0]
            faded = cutaway_fades(segment, "hanger_tree")
            c.check(name, f"{key}: Hanger tree cuts away above the player",
                    (body.get("x"), body.get("y")) == canopy and bool(faded)
                    and abs(view(d).get("height", -1) - height) < 0.1
                    and os.path.isfile(os.path.join(out, f"{key}.png")),
                    repr((body, view(d), faded)))


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


@scenario("field")
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
    plan = "ready;click:@tip:ok;wait:0.5;" + select_facing("natural") + f"sync:spot;wait:5;frame:0;view:28:5.5;lookwalk:{preset};wait:1;"
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
    if not os.environ.get("LOOK_WALK_REUSE"):
        check_facing(c, s, out, "natural")
    rows = feet_log(out)
    # Only the scenario's own frames: from its first scripted look (after the spot and the preset
    # are set). Before that the body stands wherever the last drive left it, and the first-time
    # tip's click can strike; since fov-client, `human_face` turns a standing body to the
    # cursor, so those frames turn and twist for reasons this scenario doesn't set up.
    first = re.search(r"live script: look:90 .*?, t ([\d.]+) s\)", log(out))
    start = float(first[1]) if first else float("inf")
    rows = [row for row in rows if row["t"] >= start and row.get("look") is not None]
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
    def body():
        r = subprocess.run([sys.executable, V, "sql", "--run", run, "SELECT id FROM my_body", "--as-player"], capture_output=True, text=True)
        rows = json.loads(r.stdout[r.stdout.find("["):]) if "[" in r.stdout else []
        return (rows[0]["id"] if rows else None), r.stdout
    other, t = body()
    # The run's player identity has a token from the start (`state.json`) but no character until
    # it joins: join it when it has no body.
    if other is None:
        subprocess.run([sys.executable, V, "player", "--run", run, "join", "Bender"], capture_output=True, text=True)
        other, t = body()
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


def look_walk_cursor(run, c):
    s = "look-walk:cursor"
    name = "look-walk-cursor"
    folder = os.path.join(ROOT, ".local/living/verify", run, "ui", f"{name}-{THEME}" if THEME else name)
    plan = (
        "ready;click:@tip:ok;wait:0.5;" + select_facing("cursor") +
        "sync:spot;wait:5;frame:0;look:0;wait:1;hold:90;wait:3;shot:strafe;"
        "look:270;wait:3;shot:backpedal;stop;wait:0.5;quit"
    )
    out, code, detail = drive(
        run, name, plan, syncs=[f"spot=place_at|{{me}}|{LOOK_WALK_SPOT[0]}|{LOOK_WALK_SPOT[1]}"],
        env={"LIVING_GAME_FEET": os.path.join(folder, "feet.jsonl")},
    )
    c.check(s, "client ran and joined", code == 0, detail[-300:])
    check_facing(c, s, out, "cursor")
    rows = [r for r in feet_log(out) if r.get("look") is not None and r.get("heading") is not None
            and sum(weight for _, weight in (r.get("gaits") or [])) > 0.75]
    for off, label in [(90, "strafe"), (180, "backpedal")]:
        frames = [r for r in rows if abs(abs(wrapd(r["look"] - r["heading"])) - off) < 5]
        sample = frames[-30:]
        c.check(s, f"{label}: the body points at the cursor on every sampled frame",
                len(sample) >= 10 and all(abs(wrapd(r["yaw"] - 180.0 - r["look"])) < 2 for r in sample),
                repr([(r["yaw"], r["look"], r["gaits"]) for r in sample[-3:]]))
        c.check(s, f"{label}: directional or reverse gait plays",
                any(any(("strafe" if off == 90 else "back") in gait and weight > 0.1
                        for gait, weight in r["gaits"]) for r in sample), repr([r["gaits"] for r in sample[-3:]]))


@scenario("look-walk")
def look_walk(run, c):
    """`look-walk` (play-test 5, item 2): every preset, or `LOOK_WALK_PRESETS=chest,head`;
    `LOOK_WALK_REUSE=1` checks the last drives' feet logs again, `LOOK_WALK_RECORD=1` also records
    the session (`LIVING_GAME_RECORD`, stills for a video), `LOOK_WALK_TOKEN=FILE` walks another
    character (a tired one walks at 0.6 of the pace, where the old client crossed its legs)."""
    for p in [x for x in os.environ.get("LOOK_WALK_PRESETS", "head,chest,loose").split(",") if x]:
        look_walk_one(run, c, p)
    if os.environ.get("LOOK_WALK_REUSE"):
        return
    look_walk_cursor(run, c)
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


@scenario("wheel")
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
    notes_clear(c, s, out)
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


@scenario("wheel-workplace", cullet=True)
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
    notes_clear(c, s, out)
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


@scenario("grid", cullet=True)
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
    notes_clear(c, s, out)
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


@scenario("walk-law")
def walk_law(run, c):
    """Settings › Play › Walk speed (stamina-1 made walk_base live): the row reads the world's
    `walk_base` law from the installed script and, through a play scene's admin link, writes it
    (`set_world_law`), as the authority records (`law_change`)."""
    s = "walk-law"
    plan = ("ready;wait:3;click:@menu;wait:0.4;click:@menu:Settings;wait:0.8;dump:01;shot:01_walk;"
            "click:@settings:walk:3.0;wait:4;dump:02;shot:02_walk_3;click:@settings:walk:2.6;wait:4;dump:03;"
            "sync:odd;wait:4;dump:04;shot:04_walk_2_8;sync:float;wait:4;dump:05;shot:05_walk_2_5999;click:@settings:walk:2.6;wait:4;dump:06;quit")
    # A value none of the choices is, and 2.6 written as a float reads back (admin calls, as
    # another client or an admin would set it).
    syncs = ['odd=set_world_law|"walk_base"|"2.8"', 'float=set_world_law|"walk_base"|"2.5999"']
    out, code, text = drive(run, s, plan, extra=["--admin-link"], syncs=syncs)
    c.check(s, "client ran and joined", code == 0, text[-300:])
    fs = lambda k: (((dump(out, k) or {}).get("extra") or {}).get("facing_sight") or {})
    c.check(s, "the row reads walk_base from the installed script (2.6 m/s)", abs((fs("01").get("walk") or 0) - 2.6) < 0.05 and "settings:walk:3.0" in ((dump(out, "01") or {}).get("tags") or {}), str(fs("01")))
    c.check(s, "with the admin link it can change it", fs("01").get("can_switch") is True, str(fs("01")))
    changes = [r for r in sql(run, "SELECT name, old, new FROM law_change WHERE name = 'walk_base'")]
    c.check(s, "3.0 is written as the world's law and read back", abs((fs("02").get("walk") or 0) - 3.0) < 0.05 and any(r.get("new") == "3.0" for r in changes), f"{fs('02').get('walk')}; {changes}")
    c.check(s, "and 2.6 again", abs((fs("03").get("walk") or 0) - 2.6) < 0.05 and any(r.get("new") == "2.6" for r in changes), f"{fs('03').get('walk')}; {changes}")
    # The chips (walk-chip-1): exactly the three choices, the current one selected; a value none
    # of them is, one more chip, selected; never a chip repeating a choice.
    chips = lambda k: fs(k).get("walk_chips") or []
    sel = lambda k: [l for l, on in chips(k) if on]
    c.check(s, "at 2.6: exactly the three chips, 2.6 selected", [l for l, _ in chips("03")] == ["2.6 m/s", "3.0 m/s", "3.4 m/s"] and sel("03") == ["2.6 m/s"] and sel("01") == ["2.6 m/s"] and len(chips("01")) == 3, f"{chips('01')}; {chips('03')}")
    c.check(s, "at 3.0: three chips, 3.0 selected", len(chips("02")) == 3 and sel("02") == ["3.0 m/s"], str(chips("02")))
    c.check(s, "at 2.8 (set elsewhere): four chips, the extra one 2.8, selected", [l for l, _ in chips("04")] == ["2.6 m/s", "3.0 m/s", "3.4 m/s", "2.8 m/s"] and sel("04") == ["2.8 m/s"] and "settings:walk:other" in ((dump(out, "04") or {}).get("tags") or {}), str(chips("04")))
    c.check(s, "at 2.5999: the 2.6 chip, no fourth", len(chips("05")) == 3 and sel("05") == ["2.6 m/s"] and "settings:walk:other" not in ((dump(out, "05") or {}).get("tags") or {}), f"walk {fs('05').get('walk')}; {chips('05')}")
    c.check(s, "2.6 chosen again: three chips", len(chips("06")) == 3 and sel("06") == ["2.6 m/s"], str(chips("06")))


@scenario("pools")
def pools(run, c):
    """stamina-1's pools on the bar: the focus bar ("Mana") shows always, full or short;
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
    c.check(s, "before any cast, the mana bar is shown (always shown)", "focus" in ms("00"), str(list(ms("00"))))
    f = ms("01").get("focus")
    c.check(s, "after a fire bolt it shows short", f is not None and f["value"] < f["max"], str(f))
    # The bolt's own slot cools down first (a cooldown shows before a pool), then greys too.
    heal, bolt = slot("01", "Skill2"), slot("01b", "Skill3")
    fb = ms("01b").get("focus") or {}
    c.check(s, "a slot whose pool is short of its cost greys in the rules' words (heal; the bolt once cooled down: not enough mana)", "mana" in (heal.get("off") or "").lower() and "mana" in (bolt.get("off") or "").lower() and fb.get("value", 99) < 30, str((heal.get("off"), bolt.get("off"), fb.get("value"))))
    c.check(s, "a slot of another pool is not greyed by it (strike: stamina)", "mana" not in (slot("01", "Primary").get("off") or "").lower(), str(slot("01", "Primary").get("off")))
    c.check(s, "with its max restored, the mana bar is still shown", "focus" in ms("02"), str(list(ms("02"))))


# perception-parity phase 0 (docs/PERCEPTION_PARITY_AUDIT.md, class A*): the cut points graphs
# and the rules' statuses test hunger and energy at (seeds, instincts and trials; `brain.rs`
# `starving` >= 90 and `exhausted` <= 10; `status_of`'s words).
HUNGER_CUTS = [15, 40, 45, 50, 55, 60, 80, 88, 90, 97]
ENERGY_CUTS = [10, 12, 20, 25, 30, 50, 60, 70, 85, 90]
# (hunger, energy) set on my vitals, with the rules' words expected for each.
BODY_STATES = [(10.0, 95.0, "Well fed", "Well rested"), (47.0, 40.0, "Peckish", "A little tired"), (62.0, 22.0, "Hungry", "Tired"),
               (92.0, 8.0, "Very hungry", "Exhausted"), (98.0, 55.0, "Starving", "Rested")]


@scenario("body-clock")
def body_clock(run, c):
    """Perception parity for my own hunger, energy, hour and season (class A*): graphs test the
    exact hunger and energy (`{"hunger": {"above": 55}}`, `starving`, `exhausted`) and the world's
    hour and season (`hour`, `winter`), which the HUD showed only as pills and a sky. Owner SQL
    sets my vitals across each band (the pills' words and the graphs' cut points) and the world's
    epoch to noon, 23:00, the last day of autumn and the first of winter; the cursor on the
    meters (`@body`) shows the body's tooltip, on the clock (`@clock`) the day's. Each state: the
    tooltip names every meter, hunger and energy as the whole number cut down (the number shown
    puts the value on the right side of every cut point) with the rules' word; the clock's text
    is the world's hour to the minute, a moon by the rules' night, the season and its day."""
    s = "body-clock"
    w = (sql(run, "SELECT epoch_ms, day_ms, year_days FROM world") or [{}])[0]
    if not w:
        c.check(s, "the world row", False, "no world row")
        return
    y = max(int(w["year_days"]), 4)
    winter = next(k for k in range(y) if (k * 4) // y == 3) + 1  # the first day of winter (from 1)
    vit = lambda h, e: f"sql|UPDATE vitals SET hunger = {h}, energy = {e}, at_ms = {{now_ms}}, rate_key = 0 WHERE id = {{me}}"
    syncs = ["noon=sql|UPDATE world SET epoch_ms = {epoch_at:12} WHERE id = 0"]
    plan = "ready;wait:2;sync:noon;wait:1.5;"
    for i, (h, e, _, _) in enumerate(BODY_STATES):
        syncs.append(f"v{i}={vit(h, e)}")
        plan += f"sync:v{i};wait:2.5;cursor:@body;wait:0.6;dump:v{i};" + (f"shot:v{i}_body;" if i in (1, 3) else "") + "cursor:;wait:0.3;"
    syncs += ["day=sql|UPDATE world SET epoch_ms = {epoch_at:12.25} WHERE id = 0", "night=sql|UPDATE world SET epoch_ms = {epoch_at:23.5} WHERE id = 0",
              f"autumn=sql|UPDATE world SET epoch_ms = {{epoch_at:12:{winter - 1}}} WHERE id = 0", f"winter=sql|UPDATE world SET epoch_ms = {{epoch_at:12:{winter}}} WHERE id = 0",
              f"back=sql|UPDATE world SET epoch_ms = {int(w['epoch_ms'])} WHERE id = 0;{vit(10.0, 95.0)}"]
    plan += ("sync:day;wait:1.5;dump:day;shot:day;cursor:@clock;wait:0.6;dump:day_tip;shot:day_tip;cursor:;sync:night;wait:2.5;dump:night;shot:night;"
             "sync:autumn;wait:1.5;dump:autumn;shot:autumn;sync:winter;wait:1.5;shot:winter;cursor:@clock;wait:0.6;dump:winter;shot:winter_tip;cursor:;sync:back;wait:1;quit")
    out, code, text = drive(run, s, plan, syncs=syncs)
    c.check(s, "client ran and joined", code == 0, text[-300:])
    sc = json.load(open(os.path.join(out, "scene.json"))) if os.path.exists(os.path.join(out, "scene.json")) else {}
    c.check(s, "fixtures: every owner SQL call went in", all(sc.get("snaps", {}).get(k) for k in ["noon", "day", "night", "autumn", "winter", "back"] + [f"v{i}" for i in range(len(BODY_STATES))]), str(list(sc.get("snaps", {})))[:300])
    import math
    for i, (h, e, hw, ew) in enumerate(BODY_STATES):
        d = dump(out, f"v{i}") or {}
        me = d.get("me") or {}
        body = {b["name"]: b for b in me.get("body") or []}
        tip = (d.get("extra") or {}).get("tooltip") or {}
        k = f"hunger {h:.0f}, energy {e:.0f}"
        c.check(s, f"{k}: the cursor on the meters shows the body's tooltip, as built", tip.get("title") == "Body" and tip.get("text") == me.get("body_tip") and "body" in (d.get("tags") or {}), str(tip)[:200])
        hb, eb = body.get("hunger") or {}, body.get("energy") or {}
        c.check(s, f"{k}: hunger and energy are in it though no bar shows them", hb and eb and not hb.get("shown") and not eb.get("shown") and "hunger" not in [m["name"] for m in me.get("meters") or []], str(list(body)))
        hn, en = math.floor(hb.get("value", -9) + 1e-3), math.floor(eb.get("value", -9) + 1e-3)
        text = tip.get("text") or ""
        c.check(s, f"{k}: the numbers shown are the vitals' whole numbers cut down (within the rates' drift)", f"Hunger  {hn} / 100" in text and f"Energy  {en} / 100" in text and abs(hn - h) <= 1.5 and abs(en - e) <= 1.5, text.replace("\n", " | "))
        sides = [(cut, hn >= cut, h > cut) for cut in HUNGER_CUTS] + [(-cut, en < cut, e < cut) for cut in ENERGY_CUTS]
        wrong = [cut for cut, shown, real in sides if shown != real]
        c.check(s, f"{k}: the number shown puts it on the right side of every cut point (hunger above, energy below)", not wrong, str(wrong))
        c.check(s, f"{k}: the rules' words: {hw}, {ew}", hb.get("word") == hw and eb.get("word") == ew and f"Hunger  {hn} / 100 · {hw}" in text, str((hb.get("word"), eb.get("word"))))
        pills = [p["text"] for p in me.get("statuses") or []]
        plain = {"Peckish", "Not hungry", "A little tired", "Rested"}
        c.check(s, f"{k}: the pills unchanged (a word that is not plain is a pill; a plain one is not)", all((w in pills) == (w not in plain) for w in (hw, ew)), str(pills))
    def clock_of(n):
        return (dump(out, n) or {}).get("clock") or {}
    def hour_ok(ck, want):
        t = ck.get("text") or ""
        m = int(math.floor(ck.get("hour", -1) * 60 + 1e-6))
        return abs(ck.get("hour", -9) - want) < 0.3 and t == f"{m // 60:02d}:{m % 60:02d}"
    day, tipd, night, aut, win = clock_of("day"), dump(out, "day_tip") or {}, clock_of("night"), clock_of("autumn"), clock_of("winter")
    c.check(s, "by day: the clock reads the world's hour to the minute (12:15), no night", hour_ok(day, 12.25) and day.get("night") is False, str(day))
    # The tooltip against the clock of the same dump (the world's minutes go on between dumps).
    ttip, tc = (tipd.get("extra") or {}).get("tooltip") or {}, tipd.get("clock") or {}
    c.check(s, "the cursor on the clock: its tooltip gives the day and the season's day", ttip.get("title") == f"Day {tc.get('day')} · {tc.get('text')}" and (ttip.get("text") or "").startswith(f"{tc.get('season_word')}, day {tc.get('season_day')} of {tc.get('season_days')}") and "clock" in (tipd.get("tags") or {}), str((ttip, tc)))
    c.check(s, "at night: 23:30 and night by the rules' light", hour_ok(night, 23.5) and night.get("night") is True, str(night))
    c.check(s, f"the last day of autumn (day {winter - 1} of a {y}-day year)", aut.get("season") == "autumn" and aut.get("season_day") == aut.get("season_days") and aut.get("day") == winter - 1, str(aut))
    wtip = ((dump(out, "winter") or {}).get("extra") or {}).get("tooltip") or {}
    c.check(s, "the next day is winter's first, on the clock and in its tooltip", win.get("season") == "winter" and win.get("season_word") == "Winter" and win.get("season_day") == 1 and win.get("day") == winter and (wtip.get("text") or "").startswith("Winter, day 1 of"), str((win, wtip))[:300])


@scenario("own")
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
    notes_clear(c, s, out)
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


@scenario("unheard")
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
            "point:{B};wait:0.5;key:Enter:tap;wait:0.6;dump:01;type:Can you hear me over there?;enter;wait:0.6;dump:02a;wait:1.9;shot:01_far;dump:02;wait:3.2;shot:01_after;dump:02z;"
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
    near = sorted(i for i, p in at.items() if i in people and i not in (me, b) and dist(p) < 9.5) if mine else None
    bd = round(dist(at[b]), 1) if mine and b in at else None
    c.check(s, "scene: no one else within 9.5 m of me (speech carries 9 m); the resident held beyond 9 m, within sight (11 m)", near == [] and bd is not None and 9.0 < bd <= 11.0, f"me {mine}; within 9.5 m {near}; #{b} at {bd} m")
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
    # The note and the F prompt beside the one I point at: never over each other (the prompt
    # moves to the head's other side, or waits while the note shows), and back after the note.
    notes_clear(c, s, out)
    d2 = [dump(out, k) or {} for k in ("02a", "02")]
    pz = ((dump(out, "02z") or {}).get("rects") or {}).get("prompt")
    c.check(s, "while the note shows I point at them; after it the prompt is back beside them", all((x.get("rects") or {}).get("notes") for x in d2) and any(h.get("id") == b for h in (d2[1].get("hovered") or [])) and pz is not None, f"notes {[(x.get('rects') or {}).get('notes') for x in d2]}, prompt {[(x.get('rects') or {}).get('prompt') for x in d2]}, after {pz}")
    c.check(s, "a heard line: no reach note", not any("could not have heard" in n or "near enough to hear" in n or "out of earshot" in n for n in n6), str(n6))


FAR = "someone too far away to make out"
# verify-client's far_label.py's overlay: anyone farther than 4 m is too far to make out (as
# Cullet's `perceived_of` does past 24 m), so the far case fits in view on the island.
FAR_LAW = 'fn perceived_of(p) { let r = base_perceived_of(p); if !p.self && p.dist > 4.0 { r.name = false; r.health = "none"; r.far = true; } r }'


@scenario("far")
def far(run, c):
    """far-label in the client: someone too far away to make out keeps the authority's words in
    the talk target (and the Log), while their plate and hover read "someone in blue" from the
    colours drawn; close again, "a stranger in …". The colour words are presentation only:
    nothing sent back carries them. The scene installs far_label.py's 4 m overlay of the shipped
    script (admin `install_script`) and puts the shipped script back after."""
    s = "far"
    b = residents(run, 1)[0]
    out_dir = os.path.join(ROOT, ".local/living/verify", run, "ui")
    os.makedirs(out_dir, exist_ok=True)
    shipped = open(os.path.join(ROOT, "living/scripts/skills.rhai")).read()
    overlay = os.path.join(out_dir, "far-overlay.rhai")
    open(overlay, "w").write(shipped.replace("fn perceived_of(p)", "fn base_perceived_of(p)", 1) + "\n" + FAR_LAW + "\n")
    install = os.path.join(ROOT, "living/tools/install_script.py")
    r = subprocess.run([sys.executable, install, f"verify-{run}", overlay], capture_output=True, text=True)
    c.check(s, "the 4 m overlay is installed", r.returncode == 0, (r.stdout + r.stderr)[-300:])
    line = "Hello over there."
    plan = ("ready;sync:scene;wait:2.5;point:{B};wait:0.8;shot:01_near;dump:01;"
            "sync:away;wait:3;point:{B};wait:0.8;shot:02_far;dump:02;key:Enter:tap;wait:0.6;shot:03_to_far;dump:03;"
            f"type:{line};enter;wait:1.5;dump:04;key:Escape:tap;wait:0.3;"
            "sync:back;wait:3;point:{B};wait:0.8;shot:05_close;dump:05;quit").replace("{B}", str(b))
    syncs = [f"away=place_at|{b}|(mx+6.0)|(my)", f"back=place_at|{b}|(mx+2.0)|(my)"]
    try:
        out, code, text = drive(run, s, plan, places=[f"{b}:2:0"], syncs=syncs)
    finally:
        subprocess.run([sys.executable, install, f"verify-{run}"], capture_output=True, text=True)
    c.check(s, "client ran and joined", code == 0, text[-300:])
    d = {k: dump(out, k) or {} for k in ["01", "02", "03", "04", "05"]}
    hov = lambda k: next((h.get("label") for h in d[k].get("hovered") or [] if h.get("id") == b), None)
    near1, far2, near5 = hov("01"), hov("02"), hov("05")
    # Someone drawn from a look book line is named by its words (`phrase`), made out and from
    # afar; a VRoid base (a world without looks, the island) by the projection's label and colours.
    bl = next((x.get("look") for k in d for x in (d[k] or {}).get("looks") or [] if x.get("id") == b), None)
    ph = line_phrases(bl)
    c.check(s, "close up (2 m): the plate says a stranger in their colours, or the line's words", bool(near1) and (near1.startswith("a stranger") or (ph and near1 == ph[2])) and "too far" not in near1, f"{near1!r}; phrase {ph}")
    c.check(s, "beyond the range (6 m): the plate says someone in their colours (or the line's far words), or there is none", far2 is None or re.fullmatch(r"someone in [a-z]+( [a-z]+)?( and [a-z]+( [a-z]+)?)?", far2) is not None or bool(ph and far2 == ph[2]), f"{far2!r}; hovered {d['02'].get('hovered')}; phrase {ph}")
    t3 = d["03"].get("typing") or {}
    c.check(s, "the talk target carries the authority's words", t3.get("to") == b and FAR in (t3.get("label") or "") and " in " not in (t3.get("label") or "").replace(FAR, ""), json.dumps(t3))
    L = log(out)
    said = [x for x in sql(run, f"SELECT id, kind, object, text FROM experience WHERE kind = 'said' AND object = {b}") if line in x.get("text", "")]
    c.check(s, "what I send carries my words and their id, no colour words", re.search(rf'say: "{re.escape(line)}" to #{b}\b', L) is not None and said and not any("someone in" in x.get("text", "") for x in said) and not re.search(r'(say|act)[^\n]*someone in ', L), f"{len(said)} said rows")
    c.check(s, "close again: a stranger in their colours, or the line's words", bool(near5) and (near5.startswith("a stranger") or (ph and near5 == ph[2])), f"{near5!r}")
    if ph:
        # The short outfit phrase includes the drawn form at both ranges. Talk still uses
        # the authority's neutral label when the resident is too far to make out.
        sexed = re.compile(r"\b(woman|man|girl|boy)\b")
        c.check(s, "sex-1: far (6 m), plate and hover say the short outfit phrase with the body's sex", far2 is not None and far2 == ph[2] and sexed.search(far2) is not None, f"{far2!r}; phrase {ph}")
        c.check(s, "sex-1: the far label and the talk target stay neutral (no sex word)", (t3.get("label") or "").strip() in (FAR, f"To {FAR}") or (FAR in (t3.get("label") or "") and not sexed.search((t3.get("label") or "").replace(FAR, ""))), json.dumps(t3))
        c.check(s, "sex-1: near (2 m and back at 2 m), hover shows the short outfit phrase", near1 == ph[2] and near5 == ph[2], f"{near1!r}, {near5!r}; phrase {ph}")
    notes_clear(c, s, out)


@scenario("committed")
def committed(run, c):
    """committed-moves in the client: a windup or a dash, once started, runs its whole course.
    A fire bolt (R) cast at the ground and W pressed during its windup: the authority keeps the
    windup (the bolt goes) and holds the walk, which follows once it ends; the client draws no
    movement meanwhile (the dump's `me_at`: drawn, and the authority's row). Then a dodge (`dodge:D`)
    and the guard (Q) pressed mid-dodge: the rules' refusal ("in the middle of a dodge") once,
    quietly, as a note; the dodge completes; the guard is sent but not predicted (client.log)."""
    s = "committed"
    cards = {r["skill"]: r for r in sql(run, "SELECT skill, windup_ms, recover_ms FROM skill_card")}
    wb = (cards.get("firebolt") or {}).get("windup_ms", 600) / 1000.0
    syncs = ["noon=sql|UPDATE world SET epoch_ms = {epoch_at:12} WHERE id = 0", f"spot=place_at|{{me}}|{UNHEARD_SPOT[0]}|{UNHEARD_SPOT[1]}"]
    plan = ("ready;sync:noon;sync:spot;wait:2;key:KeyX:tap;wait:0.6;cursor:0.5,0.3;wait:0.3;dump:a0;"
            f"key:KeyR:down;wait:0.08;key:KeyW:down;wait:0.05;dump:a1;wait:{max(wb / 2 - 0.13, 0.05):.2f};dump:a2;wait:{wb / 2 + 0.2:.2f};key:KeyR:up;dump:a3;"
            "wait:1.2;dump:a4;key:KeyW:up;wait:1.8;dump:b0;dodge:D;wait:0.06;key:KeyQ:down;wait:0.12;dump:b1;key:KeyQ:up;wait:1.0;shot:02_dodged;dump:b2;quit")
    out, code, text = drive(run, s, plan, syncs=syncs)
    c.check(s, "client ran and joined", code == 0, text[-300:])
    d = {k: dump(out, k) or {} for k in ("a0", "a1", "a2", "a3", "a4", "b0", "b1", "b2")}
    at = lambda k, w: ((d[k].get("me_at") or {}).get(w))
    pos = lambda k, w: (lambda v: (v["x"], v["y"]) if isinstance(v, dict) else (tuple(v) if v else None))(at(k, w))
    dist = lambda a, b: ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5 if a and b else None
    still = [dist(pos("a0", w), pos(k, w)) for k in ("a1", "a2") for w in ("body", "drawn")]
    c.check(s, "W pressed in the windup: neither the authority's body nor the drawn one moves", all(x is not None and x < 0.1 for x in still), f"windup {wb:.2f} s; moved {still}")
    # The authority row's x, y is the start of its motion segment, so a walk that starts as one long
    # segment reads 0 m on it while W is still held: judge the drawn body at a4 and the authority's
    # row at b0 (after W is let go, the stop segment starts where the walk ended).
    after = [dist(pos("a0", "drawn"), pos("a4", "drawn")), dist(pos("a0", "body"), pos("b0", "body"))]
    c.check(s, "the walk follows once the windup ends (held, then resumed)", all(x is not None and x > 0.5 for x in after), f"drawn at a4, authority at b0: {after}")
    sc = json.load(open(os.path.join(out, "scene.json"))) if os.path.exists(os.path.join(out, "scene.json")) else {}
    me = sc.get("me")
    bolts = [r for r in (sql(run, f"SELECT id, kind, skill, why FROM act_outcome WHERE observer = {me}") if me else []) if r.get("skill") == "firebolt"]
    c.check(s, "the authority kept the windup: the bolt went (its outcome told)", bool(bolts), str(bolts)[:200])
    notes = [n for k in ("a1", "a2", "a3", "a4") for n in d[k].get("notes") or []]
    c.check(s, "no note of a cancel while walking was held", not any("moved" in n.lower() or "broke off" in n.lower() for n in notes), str(notes))
    mid = [n for k in ("b1", "b2") for n in d[k].get("notes") or [] if "middle of a dodge" in n]
    c.check(s, "the guard mid-dodge: the rules' words, once, as a note", len(set(mid)) == 1 and all(n.count("middle of a dodge") == 1 for n in mid), str([d[k].get("notes") for k in ("b1", "b2")]))
    dodged = dist(pos("b0", "body"), pos("b2", "body"))
    c.check(s, "the dodge completes", dodged is not None and dodged > 1.5, f"{dodged}")
    c.check(s, "the guard was sent but not predicted", "pressed during my dodge: sent, not predicted" in log(out), "client.log")


def seed_names(run):
    """The proper names the seed this world was made from gives people and places (residents,
    their first names, buildings, plan lots and spots), from `living/seeds/<seed>.json`."""
    st = json.load(open(os.path.join(ROOT, ".local/living/verify", run, "state.json")))
    path = os.path.join(ROOT, "living/seeds", f"{st.get('seed', 'island')}.json")
    if not os.path.exists(path):
        return []
    seed = json.load(open(path))
    names = set()
    for t in seed.get("towns") or []:
        names.add(t.get("name") or "")
        for r in t.get("residents") or []:
            n = (r.get("name") or "").strip()
            names.add(n)
            first = n.split(" ")[0]
            if len(first) >= 3 and first[:1].isupper():
                names.add(first)
        for b in t.get("buildings") or []:
            names.add(b.get("name") or "")
    for plan in ((seed.get("map") or {}).get("params") or {}).get("plans") or []:
        for lot in plan.get("lots") or []:
            names.add(lot.get("name") or "")
            for sp in lot.get("spots") or []:
                names.add(sp.get("name") or "")
    # Proper names only (a capital letter): spots such as "bench by the door" or "gate" describe
    # a thing anyone sees, and would match a thing's kind.
    out = set()
    for n in names:
        n = n.strip()
        n = n[4:] if n.lower().startswith("the ") else n
        if len(n) >= 3 and any(ch.isupper() for ch in n):
            out.add(n)
    return sorted(out)


def leaked(texts, names, given):
    """Seed names found in the shown texts, but those the authority gave me (a known name, a
    place of mine). A name with a capital matches as written; a lower-case one as a phrase."""
    allowed = set()
    for g in given:
        allowed.add(g)
        allowed.update(w for w in g.split(" ") if len(w) >= 3)
    hits = []
    for where, t in texts:
        for n in names:
            if n in allowed:
                continue
            found = (n in t) if any(ch.isupper() for ch in n) else re.search(rf"\b{re.escape(n)}\b", t, re.I) is not None
            if found:
                hits.append((where, n, t[:80]))
    return hits


def naming_of(out):
    """Every dump's `naming` texts, and what the authority gave me to name."""
    texts, given = [], set()
    for f in sorted(glob.glob(os.path.join(out, "*.json"))):
        try:
            d = json.load(open(f)) or {}
        except (ValueError, OSError):
            continue
        if not isinstance(d, dict):
            continue
        texts.extend((f"{os.path.basename(f)}:{k}", t) for k, t in d.get("naming") or [])
        given.update(d.get("known_names") or [])
        given.update(d.get("given_places") or [])
    return texts, given


@scenario("names", cullet=True)
def names(run, c):
    """perceived-names-1's guard: a fresh player on a world from a named seed (Cullet) points at
    residents, opens their wheel, the talk box, the Log and its People, and a person's window. No
    text that names a person or a place on screen (the dump's `naming`) holds a seed resident's
    name, a first name, a building's or a plan lot's or spot's name the player was not given (the
    dump's `known_names`, `given_places`)."""
    s = "names"
    seeded = seed_names(run)
    c.check(s, "the seed names people and places", len(seeded) > 0, f"{len(seeded)} names")
    st = json.load(open(os.path.join(ROOT, ".local/living/verify", run, "state.json")))
    people = {r["id"] for r in sql(run, "SELECT id, kind, alive FROM character WHERE kind = 'person'") if r.get("alive")}
    bodies = [r for r in sql(run, "SELECT id, x, y FROM body") if r["id"] in people]
    arrive = (sql(run, "SELECT arrive_x, arrive_y FROM land") or [{}])[0]
    ax, ay = arrive.get("arrive_x", 0.0), arrive.get("arrive_y", 0.0)
    near = sorted(bodies, key=lambda r: (r["x"] - ax) ** 2 + (r["y"] - ay) ** 2)[:4]
    steps = "".join(f"point:{r['id']};wait:0.7;dump:p{i};key:KeyF:down;wait:0.7;dump:w{i};key:KeyF:up;wait:0.2;key:Escape:tap;wait:0.3;"
                    f"point:{r['id']};wait:0.4;key:Enter:tap;wait:0.6;dump:t{i};key:Escape:tap;wait:0.3;" for i, r in enumerate(near))
    plan = ("ready;wait:5;dump:00;" + steps + "key:KeyL:tap;wait:0.6;dump:log;click:@log:tab:1;wait:0.6;dump:people;click:@log:person:0;wait:0.8;dump:window;"
            "click:@log:tab:2;wait:0.5;dump:events;quit")
    token = os.path.join(ROOT, ".local/living/verify", run, "ui", f"names-{int(time.time())}.token")
    # The earshot law on, so the authority's sentence (in the talk box's hint line) is scanned too.
    call_admin(run, "set_world_law", ["earshot", "true"])
    try:
        out, code, text = drive(run, s, plan, extra=["--token", token, "--player", "Newcomer"])
    finally:
        call_admin(run, "set_world_law", ["earshot", "false"])
    c.check(s, "client ran and joined (a fresh player)", code == 0, text[-300:])
    texts, given = naming_of(out)
    kinds = {w.split(":")[1] for w, _ in texts}
    c.check(s, "names were on screen: plates, the talk box, the Log, the earshot sentence", {"plate", "talk", "earshot"} <= kinds, f"{sorted(kinds)}; {len(texts)} texts; residents pointed at {[r['id'] for r in near]}")
    hits = leaked(texts, seeded, given)
    c.check(s, "no person or place is named by a seed name the player was not given", not hits, f"{hits[:6]}; given {sorted(given)[:8]}")


@scenario("death")
def death(run, c):
    """The death screen names no one it should not (perceived-names-1). An admin's `kill` whose
    cause names a resident (code `other`) says "You died", not the cause; killed by a stranger
    (verify.py's player identity, striking with the scene's sharper, free strike) says "Killed by"
    the stranger as perceived ("a stranger in …"), never their name. Each drive is a fresh player."""
    s = "death"
    rid = residents(run, 1)[0]
    real = (sql(run, f"SELECT id, name FROM character WHERE id = {rid}") or [{}])[0].get("name", "")
    d = os.path.join(ROOT, ".local/living/verify", run, "ui")
    os.makedirs(d, exist_ok=True)
    tok = lambda k: os.path.join(d, f"death-{k}-{int(time.time())}.token")
    # 1. An admin's cause that names someone.
    plan = "ready;wait:3;dump:00;sync:kill;wait:3;shot:01_died;dump:01;quit"
    out, code, text = drive(run, "death-other", plan, syncs=[f'kill=kill|{{me}}|"killed by {real}"'], extra=["--token", tok("other"), "--player", "Fallen"])
    c.check(s, "client ran and joined (killed by the admin)", code == 0, text[-300:])
    dt = (dump(out, "01") or {})
    words = [t for k, t in dt.get("naming") or [] if k == "death"]
    c.check(s, "a cause that names someone: the screen says only You died", words[:1] == ["You died"] and not any(real and real in t for _, t in dt.get("naming") or []), f"{words}; resident {real!r}")
    # 2. Killed by a stranger.
    subprocess.run([sys.executable, V, "player", "--run", run, "join", "Striker"], capture_output=True, text=True)
    me2 = (sql_as_player(run, "SELECT * FROM my_characters") or [{}])
    striker = next((r["id"] for r in me2 if r.get("alive")), None)
    sname = next((r.get("name") for r in me2 if r.get("id") == striker), "Striker")
    c.check(s, "the stranger who strikes is a living player character", striker is not None, str(me2)[:200])
    # A sync runs once per name (drive.py waits for NAME.go): one name per strike.
    hits = "".join(f"sync:hit{i};wait:0.9;" for i in range(8))
    plan = "ready;wait:3;sync:sharp;sync:near;wait:1.5;dump:00;" + hits + "wait:2;shot:02_killed;dump:02;sync:blunt;quit"
    syncs = ['sharp=set_world_law|"dmg_strike"|"40";set_world_law|"cost_strike"|"0"', f"near=place_at|{striker}|(mx+0.9)|(my)",
             *[f'hit{i}=player|use_skill|strike|{{me}}|(mx)|(my)' for i in range(8)], 'blunt=set_world_law|"dmg_strike"|"5";set_world_law|"cost_strike"|"20"']
    try:
        out, code, text = drive(run, "death-struck", plan, syncs=syncs, extra=["--token", tok("struck"), "--player", "Struck"])
    finally:
        call_admin(run, "set_world_law", ["dmg_strike", "5"])
        call_admin(run, "set_world_law", ["cost_strike", "20"])
    c.check(s, "client ran and joined (struck)", code == 0, text[-300:])
    dt = (dump(out, "02") or {})
    words = [t for k, t in dt.get("naming") or [] if k == "death"]
    # As perceived: "a stranger in …" on a world without looks, the striker's line's words where they
    # have a look (`phrase`; a player gets a pool look on a world with looks).
    sl = (look_rows(run) or {}).get(striker)
    ph = line_phrases(sl)
    seen_as = ["Killed by a stranger"] + ([f"Killed by {ph[0]}", f"Killed by {ph[1]}"] if ph else [])
    c.check(s, "killed by a stranger: named as perceived, never by their name", bool(words) and any(words[0].startswith(x) for x in seen_as) and not any(sname and sname in t for _, t in dt.get("naming") or []), f"{words}; striker {sname!r}; as perceived {seen_as}")


@scenario("houses")
def houses(run, c):
    """owner-known in the client: a structure is named by its kind, "{name}'s {kind}" only once
    my character knows the owner by name (`my_known_names`), "your {kind}" when mine. The scene
    holds a resident beside the arrival and puts a house by them (admin `place_structure`: owned
    by them); a fresh player points at it ("house"); the resident says their name to the player
    (admin `mind_say`, the speech minds use: an introduction), and it reads "{name}'s house"; a
    house put by the player reads "your house"."""
    s = "houses"
    b = residents(run, 1)[0]
    bname = (sql(run, f"SELECT id, name FROM character WHERE id = {b}") or [{}])[0].get("name", "")
    # On open grass, cleared (anyone within 25 m put 40 m east): the cursor's aim takes a body
    # before a thing, so neither the owner nor I stand by a house when it is pointed at.
    ax, ay = UNHEARD_SPOT
    people = {r["id"]: r.get("name") for r in sql(run, "SELECT id, name, kind FROM character WHERE kind = 'person'")}
    for i, r in enumerate(x for x in sql(run, "SELECT id, x, y FROM body") if x["id"] in people and x["id"] != b and people[x["id"]] != "Verifier" and ((x["x"] - ax) ** 2 + (x["y"] - ay) ** 2) ** 0.5 < 25):
        call_admin(run, "place_at", [r["id"], ax + 40, ay + 3 * i])
    call_admin(run, "set_behavior", [b, json.dumps({"wait": 600})])
    call_admin(run, "place_at", [b, ax + 4.0, ay + 4.0])
    time.sleep(1.0)
    before = {r["id"] for r in sql(run, "SELECT id FROM structure")}
    call_admin(run, "place_structure", [b, "house"])
    theirs = [r for r in sql(run, f"SELECT id, kind, owner, x, y FROM structure WHERE owner = {b}") if r["id"] not in before]
    c.check(s, "a house of the resident's on the cleared spot", len(theirs) == 1, str(theirs))
    if not theirs:
        return
    # Off the house, within the 9 m speech carries to where I will stand (their name must reach me).
    call_admin(run, "place_at", [b, ax + 5.0, ay - 3.0])
    h = theirs[0]
    thought = json.dumps({"kind": "talk", "summary": "", "detail": "", "latency_ms": 0, "tokens": 0, "model": "verify-ui scene", "reference": ""})
    syncs = ["noon=sql|UPDATE world SET epoch_ms = {epoch_at:12} WHERE id = 0", f"spot=place_at|{{me}}|{ax}|{ay}", f'intro=mind_say|{b}|"I\'m {bname}."|{{me}}|""|0|{thought}',
             'mine=place_structure|{me}|"house"', f"off=place_at|{{me}}|{ax - 3.0}|{ay}"]
    plan = (f"ready;sync:noon;wait:1;sync:spot;wait:2;pointat:{h['x']},{h['y']};wait:1.2;shot:01_house;dump:01;"
            f"sync:intro;wait:3;pointat:{h['x']},{h['y']};wait:1.2;shot:02_theirs;dump:02;"
            f"sync:mine;wait:1;sync:off;wait:2;pointat:{ax + 0.8},{ay};wait:1.2;shot:03_mine;dump:03;quit")
    tok = os.path.join(ROOT, ".local/living/verify", run, "ui", f"houses-{int(time.time())}.token")
    out, code, text = drive(run, s, plan, syncs=syncs, extra=["--token", tok, "--player", "Lodger"])
    c.check(s, "client ran and joined (a fresh player)", code == 0, text[-300:])
    aim = lambda k: [t for w, t in (dump(out, k) or {}).get("naming") or [] if w == "aim"]
    every = [t for k in ("01", "02", "03") for _, t in (dump(out, k) or {}).get("naming") or []]
    c.check(s, "a stranger's house: the kind alone, no owner", aim("01") == ["house"] and not any(bname in t for _, t in (dump(out, "01") or {}).get("naming") or []), f"{aim('01')}; owner {bname!r}")
    known = (dump(out, "02") or {}).get("known_names") or []
    c.check(s, "told their name, I know them (my_known_names)", bname in known, f"{bname!r} in {known[:8]}")
    c.check(s, "then it is their house, by name", aim("02") == [f"{bname}'s house"], str(aim("02")))
    c.check(s, "a house of mine: your house", aim("03") == ["your house"], str(aim("03")))


@scenario("shot")
def shot(run, c):
    """fix-missile-told in the client: an arrow on me is told as a shot, by the shooter as my
    character perceives them when it sees them, else by the arrow alone; the weapon's note is
    that line ("A stranger shot you with an arrow: hit for 7. Your weapon is drawn."), never an
    "attacked" of ours beside it; an unseen shooter (the feed's id 0) is named, targeted and
    plated by nothing. verify.py's player identity ("Striker", given a bow and arrows, held still)
    shoots a fresh player at noon on open grass from 6 m (in sight), then, the weapon sheathed
    again, from 16 m (beyond the 11 m one sees by day, within the bow's 22)."""
    s = "shot"
    subprocess.run([sys.executable, V, "player", "--run", run, "join", "Striker"], capture_output=True, text=True)
    mine = sql_as_player(run, "SELECT * FROM my_characters")
    striker = next((r["id"] for r in mine if r.get("alive")), None)
    sname = next((r.get("name") for r in mine if r.get("id") == striker), "Striker")
    c.check(s, "the shooter is a living player character", striker is not None, str(mine)[:200])
    if striker is None:
        return
    for item, n in (("bow", 1), ("arrow", 6)):
        call_admin(run, "grant_items", [striker, item, n])
    call_admin(run, "set_behavior", [striker, json.dumps({"wait": 600})])
    syncs = ["noon=sql|UPDATE world SET epoch_ms = {epoch_at:12} WHERE id = 0", f"spot=place_at|{{me}}|{UNHEARD_SPOT[0]}|{UNHEARD_SPOT[1]}",
             f"near=place_at|{striker}|(mx+6.0)|(my)", f"far=place_at|{striker}|(mx+16.0)|(my)", "shoot1=player|use_skill|bowshot|{me}|(mx)|(my)", "shoot2=player|use_skill|bowshot|{me}|(mx)|(my)",
             "hurt1=sql|SELECT id, hurt_by, hurt_ms FROM vitals WHERE id = {me}", "hurt2=sql|SELECT id, hurt_by, hurt_ms FROM vitals WHERE id = {me}"]
    plan = ("ready;sync:noon;sync:spot;wait:2;sync:near;wait:2;dump:00;sync:shoot1;wait:2.2;sync:hurt1;shot:01_seen;dump:01;"
            "weapon:sheathe;wait:0.6;sync:far;wait:2.5;dump:02;sync:shoot2;wait:2.5;sync:hurt2;shot:02_unseen;dump:03;quit")
    tok = os.path.join(ROOT, ".local/living/verify", run, "ui", f"shot-{int(time.time())}.token")
    out, code, text = drive(run, s, plan, syncs=syncs, extra=["--token", tok, "--player", "Target"])
    c.check(s, "client ran and joined (a fresh player)", code == 0, text[-300:])
    d = {k: dump(out, k) or {} for k in ("00", "01", "02", "03")}
    seen = lambda k: set(d[k].get("perceived") or [])
    sc = json.load(open(os.path.join(out, "scene.json"))) if os.path.exists(os.path.join(out, "scene.json")) else {}
    me = sc.get("me")
    lines = sorted(sql(run, f"SELECT id, kind, subject, text, at_ms FROM experience WHERE observer = {me} AND kind = 'attacked'") if me else [], key=lambda r: r["at_ms"])
    c.check(s, "the authority told both arrows as shots: by the shooter in sight, by the arrow alone unseen", len(lines) >= 2 and "shot you with" in lines[0]["text"] and lines[0]["subject"] == striker and "could not see" in lines[-1]["text"] and lines[-1]["subject"] == 0, str([(l["subject"], l["text"]) for l in lines])[:400])
    n1 = d["01"].get("notes") or []
    c.check(s, "in sight: the shooter is seen, and the note is the authority's shot, the weapon drawn", striker in seen("00") and any("shot you with" in n and "Your weapon is drawn" in n for n in n1) and not any("attacked you" in n for n in n1) and (d["01"].get("extra") or {}).get("drawn") is True, f"{n1}; seen {sorted(seen('00'))}")
    n3 = d["03"].get("notes") or []
    c.check(s, "out of sight: the shooter is not seen, and the note says the arrow came from somewhere unseen", striker not in seen("02") and any("could not see" in n for n in n3) and (d["03"].get("extra") or {}).get("drawn") is True, f"{n3}; seen {sorted(seen('02'))}")
    # fix-unseen-killer-id: `my_vitals.hurt_by` names the shooter only when my character sees them.
    hurt = lambda k: ((((sc.get("snaps") or {}).get(k) or [{}])[0].get("rows") or [{}])[0])
    h1, h2 = hurt("hurt1"), hurt("hurt2")
    c.check(s, "hurt_by: the shooter in sight, 0 once unseen (a newer hurt)", h1.get("hurt_by") == striker and h2.get("hurt_by") == 0 and h2.get("hurt_ms", 0) > h1.get("hurt_ms", 0), f"{h1}; {h2}")
    c.check(s, "nothing targets or hovers the hidden shooter, and the target plate is not theirs", d["03"].get("targeted") != striker and not any(h.get("id") == striker for h in d["03"].get("hovered") or []), f"targeted {d['03'].get('targeted')}; hovered {d['03'].get('hovered')}")
    c.check(s, "the shooter's name is nowhere", not any(sname in t for k in d for _, t in d[k].get("naming") or []), sname)


LOOK_BOOK = os.path.join(ROOT, "living/game/assets/characters/looks.json")


def outer_piece(line, upper, outfit=None):
    """The chip `looks.rs` reads from a line: its outermost upper (or lower) piece's colour, by
    each outfit style's slot and layer (`style_places`), else the pieces' names with char-4's
    values. Trim, feet and head pieces give no chip."""
    import re as _re
    ranks = {"jersey": 0, "jersey_smock": 0, "jersey_coat": 0, "smock": 1, "coat": 1, "apron": 3} if upper else {"trousers": 0, "skirt": 0}
    want = "upper" if upper else "lower"
    best = None
    for piece in line.get("styles", {}).get("outfit", []):
        if outfit and piece in outfit:
            o = outfit[piece]
            rank = o["layer"] if o["slot"] == want and not o.get("trim") else None
        else:
            rank = ranks.get(_re.sub(r"_\d+$", "", piece.removesuffix("-f").removesuffix("-m")))
        if rank is not None and (best is None or rank > best[0]):
            best = (rank, piece)
    return line.get("colors", {}).get("outfit", {}).get(best[1]) if best else None


BANDS = {"child": 1, "youth": 2, "adult": 3, "elder": 4}


def style_places(line):
    """Each outfit piece's place from its style file's scene extras, `outfit: {piece, slot,
    layer, trim}` (char-4's)."""
    import struct
    out = {}
    for piece in line.get("styles", {}).get("outfit", []):
        path = os.path.join(ROOT, "living/game/assets/lookdev/styles/outfit", f"{piece}.glb")
        try:
            raw = open(path, "rb").read()
            j = json.loads(raw[20:20 + struct.unpack("<I", raw[12:16])[0]])
        except (OSError, ValueError):
            continue
        o = ((j.get("scenes") or [{}])[j.get("scene", 0)].get("extras") or {}).get("outfit")
        if isinstance(o, dict) and isinstance(o.get("slot"), str):
            out[piece] = {"slot": o["slot"], "layer": int(o.get("layer", 0)), "trim": bool(o.get("trim"))}
    return out


def look_phrase(words, seen, band):
    """`living_rules::look::phrase` (living/rules/src/look.rs), the words a person drawn from a look
    book line is labelled by: `seen` "full" (made out) or "far"; `band` 1 child .. 4 elder."""
    if seen == "full":
        noun = (words.get("form") or "").strip() or "person"
    elif (words.get("form") or "").strip().split(" ")[-1:] in (["woman"], ["man"], ["girl"], ["boy"]):
        # A far figure's form says its sex (sex-1): it is drawn in full on the screen.
        noun = words["form"].strip()
    else:
        noun = "child" if band <= 1 else ("old figure" if band == 4 else "figure")
    head = {0: "short ", 2: "tall "}.get(words.get("height", 1), "") + noun
    out = f"{'an' if head[0] in 'aeiou' else 'a'} {head}"
    clothes = [x for x in ((words.get("top") or "").strip(), (words.get("bottom") or "").strip()) if x]
    if clothes:
        out += " in " + " and ".join(clothes)
    if seen == "full" and (words.get("hair") or "").strip():
        out += ", " + words["hair"].strip()
    out += {0: ", slight", 2: ", heavy-set"}.get(words.get("girth", 1), "")
    if (words.get("head") or "").strip():
        out += ", in " + words["head"].strip()
    if seen == "full" and (words.get("beard") or "").strip():
        out += ", with " + words["beard"].strip()
    return out


def line_phrases(key):
    """What the client calls someone drawn from `key`'s line, made out and from afar; None for no
    key or a key the book lacks (a VRoid base: colour words)."""
    if not key or not os.path.exists(LOOK_BOOK):
        return None
    line = json.load(open(LOOK_BOOK))["lines"].get(key)
    if not line:
        return None
    band = BANDS.get(line["person"]["type"].split("-")[0], 3)
    words = line.get("words") or {}
    short = {"form": words.get("form", ""), "top": words.get("top", "").split(" with ", 1)[0]}
    return look_phrase(words, "full", band), look_phrase(words, "far", band), look_phrase(short, "far", band)


def look_rows(run):
    """The authority's truth (owner SQL on the private `look` table): each person's line key."""
    return {r["id"]: r["line"] for r in sql(run, "SELECT id, line FROM look")}


def book_copy(out, book, name, drop=(), generation=None):
    """A test's copy of the look book (`LIVING_GAME_LOOK_BOOK`): lines left out, another generation."""
    b = json.loads(json.dumps(book))
    for k in drop:
        b["lines"].pop(k, None)
    b["decor"] = [k for k in b.get("decor", []) if k not in drop]
    if generation:
        b["generation"], b["generations"] = generation, [generation]
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, f"{name}.looks.json")
    json.dump(b, open(path, "w"))
    return path


@scenario("looks", cullet=True)
def looks(run, c):
    """look-1 (docs/LOOK.md §5, §7) on a Cullet world, whose genesis gives every resident a look
    row: everyone drawn from their projected key, each key the authority's own (`look.line`), and
    my own character from my own row. Two residents beside me (`sync:scene`): A drawn from its
    line, B's line left out of the client's book (a test copy, `LIVING_GAME_LOOK_BOOK`), so B is
    a VRoid base with one warning line. Chips by the style files' slot and layer. A second drive
    with a book of another generation (one warning at connect), and a look-dev island tour whose
    background people wear decor lines only."""
    s = "looks"
    if not os.path.exists(LOOK_BOOK):
        c.check(s, "a look book is on disk", False, LOOK_BOOK)
        return
    book = json.load(open(LOOK_BOOK))
    world = (sql(run, "SELECT look_book FROM world") or [{}])[0].get("look_book", "")
    rows = look_rows(run)
    c.check(s, "the world has looks the book holds", world and (world == book["generation"] or world in book.get("generations", [])) and rows and all(k in book["lines"] for k in rows.values()),
            f"world {world!r}, book {book['generation']!r}; {len(rows)} look rows, {sum(1 for k in rows.values() if k not in book['lines'])} not in the book")
    a, b = residents(run, 2)
    ev = os.path.join(ROOT, ".local/living/verify", run, "ui")
    test_book = book_copy(ev, book, "looks-without-b", drop=[rows.get(b, "")])
    # Start on open ground even if the previous scenario left the player beside Cullet's hedge.
    plan = (f"ready;sync:open_ground;look:0;sync:scene;cursor:0.5,0.5;wait:5;"
            f"dump:00;shot:00_drawn;sync:hold;wait:0.6;point:{a};wait:0.5;dump:01;quit")
    with resident_fixture(run, (a, b)):
        out, code, text = drive(run, s, plan, free=[f"{a}:-2.0:-1.5", f"{b}:2.0:-1.5"],
                                syncs=["open_ground=place_at|{me}|781.5|469.5", "hold=refree"],
                                env={"LIVING_GAME_LOOK_BOOK": test_book})
    c.check(s, "client ran and joined", code == 0, text[-300:])
    L = log(out)
    d0 = dump(out, "00") or {}
    seen0 = {x["id"] for x in d0.get("seen") or []}
    c.check(s, "scene: both residents are in view", {a, b} <= seen0, f"{a}, {b} in view {sorted(seen0)}")
    rows = look_rows(run)
    by = {x["id"]: x for x in d0.get("looks") or []}
    held = json.load(open(test_book))["lines"]
    la, lb = by.get(a, {}), by.get(b, {})
    c.check(s, "a resident is drawn from the line its row names", la.get("composed") is True and la.get("look") == rows.get(a), f"{json.dumps(la)}; row {rows.get(a)}")
    wrong = [(x["id"], x.get("look"), rows.get(x["id"])) for x in by.values() if x.get("look") != rows.get(x["id"], "")]
    c.check(s, "every person drawn carries the key the authority holds for them", by and not wrong, f"{len(by)} drawn; differing {wrong[:3]}")
    c.check(s, "every key the book holds is drawn composed, every other as a VRoid base", all(x.get("composed") == (x.get("look") in held) for x in by.values()), json.dumps([x for x in by.values() if x.get("composed") != (x.get("look") in held)][:3]))
    c.check(s, "a key the book lacks: a VRoid base, one warning line", lb.get("composed") is False and lb.get("look") == rows.get(b) and L.count(f"looks: {rows.get(b)} is not in the look book") == 1, f"{json.dumps(lb)}; {L.count('is not in the look book')} warnings")
    c.check(s, "no warning for people without a key, nor for the generation", "people without a look key" not in L and "was made with look generation" not in L)
    composed = [x for x in by.values() if x.get("composed")]
    sc = json.load(open(os.path.join(out, "scene.json"))) if os.path.exists(os.path.join(out, "scene.json")) else {}
    me_id = sc.get("me")
    chips = lambda key: [outer_piece(book["lines"][key]["person"], True, style_places(book["lines"][key]["person"])), outer_piece(book["lines"][key]["person"], False, style_places(book["lines"][key]["person"]))]
    # My own chips are not kept (the labels are for others).
    off = [(x["id"], x.get("chips"), chips(x["look"])) for x in composed if x["id"] != me_id and (x.get("chips") or [None, None]) != chips(x["look"])]
    c.check(s, "chips by piece: a composed person's chips are its line's outermost upper and lower pieces' colours", composed and not off, f"{off[:3]}")
    files = book.get("files") or {}
    worn = {p for x in composed for p in book["lines"][x["look"]]["person"].get("styles", {}).get("outfit", [])}
    places = {p: v for x in composed for p, v in style_places(book["lines"][x["look"]]["person"]).items()}
    differ = [(p, places.get(p), files.get(f"styles/outfit/{p}")) for p in sorted(worn) if f"styles/outfit/{p}" in files and (files[f"styles/outfit/{p}"].get("slot"), files[f"styles/outfit/{p}"].get("layer")) != ((places.get(p) or {}).get("slot"), (places.get(p) or {}).get("layer"))]
    c.check(s, "every worn outfit style carries its slot and layer, as the book's files list them", worn and set(places) == worn and not differ, f"{len(places)} of {len(worn)} with extras; differing {differ[:3]}")
    mine = by.get(me_id, {})
    c.check(s, "my own look comes from my own row", mine.get("composed") is True and mine.get("look") == rows.get(me_id), f"me {me_id}: {json.dumps(mine)}; row {rows.get(me_id)}")
    # Labels by the line's words (`phrase`): A, pointed at, is named as a mind is told; no plate
    # on screen carries a seed name.
    d1 = dump(out, "01") or {}
    hov = next((h.get("label") for h in d1.get("hovered") or [] if h.get("id") == a), None)
    want = (line_phrases(rows.get(a)) or (None, None, None))[2]
    plates = [t for k, t in (d0.get("naming") or []) + (d1.get("naming") or []) if k == "plate"]
    c.check(s, "labels by the line's words (phrase), no name", hov is not None and hov == want and plates and not any(n and n in " ".join(plates) for n in seed_names(run)), f"hovered {hov!r}, phrase {want!r}; {len(plates)} plates {plates[:3]}")
    # 2. A book of another generation.
    other = book_copy(ev, book, "looks-other-generation", generation="c4-not-this-book")
    out2, code2, text2 = drive(run, "looks-generation", "ready;wait:4;dump:00;quit", env={"LIVING_GAME_LOOK_BOOK": other})
    L2 = log(out2)
    c.check(s, "a world generation the book does not hold: one warning at connect", code2 == 0 and L2.count(f"looks: the world was made with look generation {world}") == 1, text2[-200:])
    # 3. Background people on the look-dev island: from the decor lines only.
    decor_lines = set(book.get("decor", []))
    wearable = set(book["lines"]) - decor_lines
    tour = os.path.join(ROOT, ".local/living/verify", run, "ui", "looks-decor")
    os.makedirs(tour, exist_ok=True)
    client = os.path.join(os.environ.get("CARGO_TARGET_DIR", os.path.join(ROOT, ".local/target")), "release/living-game")
    e3 = dict(os.environ, LIVING_GAME_LOOKDEV="1", LIVING_GAME_TOUR=tour, LIVING_GAME_TOUR_ONLY="island", LIVING_GAME_TOUR_SHOTS="default", LIVING_GAME_SIZE="1280x720",
              RUST_LOG="info,wgpu=warn,naga=warn,living_game::island=debug")
    with open(os.path.join(tour, "client.log"), "w") as f:
        r3 = subprocess.run([client], env=e3, stdout=f, stderr=subprocess.STDOUT, cwd=ROOT, timeout=600)
    drawn = re.findall(r"looks: background person \S+ drawn from decor (lk_[0-9a-f]{16})", log(tour))
    c.check(s, "background people are drawn from the decor lines, never a line a character wears", r3.returncode == 0 and drawn and set(drawn) <= decor_lines and not set(drawn) & wearable,
            f"{len(drawn)} drawn, {len(set(drawn))} lines; outside decor {sorted(set(drawn) - decor_lines)[:3]}")


@scenario("looks-old")
def looks_old(run, c):
    """look-1 on a world made without looks (no look rows and an empty `world.look_book`):
    everyone drawn as a VRoid base, quietly, with one line at connect. Every shipped seed carries
    looks since look-1-island, so the world is the island's seed without them (`looks_seed.py RUN
    --old`, then launch with it fresh)."""
    s = "looks-old"
    world = (sql(run, "SELECT look_book FROM world") or [{}])[0].get("look_book", "")
    c.check(s, "the world has no looks", world == "" and not look_rows(run), f"look_book {world!r}; make it with looks_seed.py {run} --old")
    out, code, text = drive(run, s, "ready;cursor:0.5,0.5;wait:5;dump:00;quit")
    L = log(out)
    by = {x["id"]: x for x in (dump(out, "00") or {}).get("looks") or []}
    warned = [l for l in L.splitlines() if "looks:" in l and "WARN" in l]
    c.check(s, "everyone a VRoid base without a key, one line at connect, no warning", code == 0 and by and not any(x.get("composed") or x.get("look") for x in by.values()) and L.count("looks: this world was made before looks") == 1 and not warned,
            f"{len(by)} drawn; {L.count('made before looks')} connect lines; warnings {warned[:2]}")


@scenario("looks-band", cullet=True)
def looks_band(run, c):
    """A band change redrawn in place, on a Cullet world at a lab pace (`looks_seed.py RUN`, then
    launch with its seed: a year every 20 s). Three residents whose bands change in the first
    minute are held beside me; a burst of dumps 0.2 s apart for 70 s. Each key change seen is
    the authority's new line, composed before and after, drawn in every dump through it and
    never jumping on screen."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("looks_seed", os.path.join(HERE, "looks_seed.py"))
    ls = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ls)
    s = "looks-band"
    w = (sql(run, "SELECT life_pace, year_days, look_book FROM world") or [{}])[0]
    c.check(s, "the world runs at the lab pace", abs(w.get("life_pace", 0) - ls.PACE) < 1e-6 and w.get("year_days") == 1, f"{w}; make it with looks_seed.py {run}")
    if abs(w.get("life_pace", 0) - ls.PACE) >= 1e-6:
        return
    people = {r["name"]: r["id"] for r in sql(run, "SELECT id, name, alive FROM character WHERE kind = 'person'") if r.get("alive")}
    ids = [people[n] for n in ls.CHANGERS if n in people][1:4]
    before = look_rows(run)
    burst = "".join(f"dump:b{i:03d};wait:0.2;" + (f"shot:b{i:03d};" if i % 10 == 0 else "") for i in range(350))
    plan = f"ready;sync:scene;cursor:0.5,0.5;wait:1;{burst}quit"
    with resident_fixture(run, ids):
        out, code, text = drive(run, s, plan, free=[f"{ids[0]}:-2.5:1.0", f"{ids[1]}:2.0:-1.0", f"{ids[2]}:0.5:2.2"])
    c.check(s, "client ran and joined", code == 0, text[-300:])
    after = look_rows(run)
    L = log(out)
    dumps = [dump(out, f"b{i:03d}") or {} for i in range(350)]
    changes = []
    for pid in ids:
        keys = [next((x for x in d.get("looks") or [] if x["id"] == pid), None) for d in dumps]
        for i in range(1, len(keys)):
            if keys[i] and keys[i - 1] and keys[i]["look"] != keys[i - 1]["look"]:
                changes.append((pid, i, keys[i - 1]["look"], keys[i]["look"]))
    c.check(s, "a band change seen: a resident beside me took a new key", changes, f"{len(changes)} changes among {ids}; rows changed {[k for k in ids if before.get(k) != after.get(k)]}")
    for pid, i, old, new in changes:
        lo, hi = max(0, i - 10), min(len(dumps), i + 15)
        win = dumps[lo:hi]
        looks_w = [next((x for x in d.get("looks") or [] if x["id"] == pid), {}) for d in win]
        feet = [next((x["feet"] for x in d.get("seen") or [] if x["id"] == pid), None) for d in win]
        steps = [round(((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2) ** 0.5) for p, q in zip(feet, feet[1:]) if p and q]
        c.check(s, f"#{pid} redrawn in place for its new line", new == after.get(pid) and all(x.get("composed") for x in looks_w) and all(feet) and steps and max(steps) <= 60 and f"looks: #{pid} redrawn for a new look ({old} → {new})" in L,
                f"{old} → {new} (row {after.get(pid)}); composed {[x.get('composed') for x in looks_w].count(True)}/{len(looks_w)}; in view {sum(1 for f in feet if f)}/{len(feet)}; largest step {max(steps) if steps else None} px")


@scenario("skirt-scale")
def skirt_scale(run, c):
    """A spring skirt on a scaled body (`characters::shape`: a `J_Sec_` bone under a bone with its
    own scale takes that scale, compose-skirt-scale). No world: the asset view poses VRoid bases
    from the tracked recipes on one fixed frame (`idle@0.5`, front) and writes every bone's place
    (`LIVING_GAME_VIEW_JOINTS`). The skirt chains' `_end` joints sit at the hem: its height as a
    share of the thigh, (upper leg - hem) / (upper leg - knee), and its width as a share of the upper
    legs' span. Shino at legs 1.05 and girth 1.05 (`ranger`) keeps Shino's share and width at
    scale 1 (`shino`); Vivi at legs 0.66, hips 1.15 and girth 1.35 (`small`) keeps Vivi's width
    (`vivi`; her side chains hang from the hips, whose own scale leaves height at 1, so her share is
    not asserted). On main's client before the change `ranger`'s hem stood 0.012 of the thigh too
    high and `small`'s skirt 13% too narrow."""
    s = "skirt-scale"
    client = os.path.join(os.environ.get("CARGO_TARGET_DIR", os.path.join(ROOT, ".local/target")), "release/living-game")
    out = os.path.join(ROOT, ".local/living/verify", run, "ui", s)
    os.makedirs(out, exist_ok=True)
    joints = os.path.join(out, "joints.jsonl")
    if os.path.exists(joints):
        os.remove(joints)
    env = dict(os.environ, LIVING_GAME_VIEW="recipe:shino,recipe:ranger,recipe:vivi,recipe:small", LIVING_GAME_VIEW_OUT=out, LIVING_GAME_VIEW_SHOTS="idle@0.5/front", LIVING_GAME_VIEW_CLIP="idle", LIVING_GAME_VIEW_JOINTS=joints)
    r = subprocess.run([client], capture_output=True, text=True, env=env, timeout=300)
    open(os.path.join(out, "view.log"), "w").write(r.stdout + r.stderr)
    by = {}
    if os.path.exists(joints):
        for line in open(joints):
            d = json.loads(line)
            by[d["file"]] = d["joints"]
    c.check(s, "the asset view posed the four", r.returncode == 0 and all(f"recipe:{n}" in by for n in ("shino", "ranger", "vivi", "small")), f"rc {r.returncode}; {sorted(by)}")

    def hem(j):
        ends = [v for k, v in j.items() if "Skirt" in k and k.endswith("_end")]
        if not ends or "J_Bip_L_UpperLeg" not in j:
            return None
        up = (j["J_Bip_L_UpperLeg"][1] + j["J_Bip_R_UpperLeg"][1]) / 2
        knee = (j["J_Bip_L_LowerLeg"][1] + j["J_Bip_R_LowerLeg"][1]) / 2
        y = sum(v[1] for v in ends) / len(ends)
        span = abs(j["J_Bip_L_UpperLeg"][0] - j["J_Bip_R_UpperLeg"][0])
        return (up - y) / (up - knee), (max(v[0] for v in ends) - min(v[0] for v in ends)) / span

    h = {n: hem(by.get(f"recipe:{n}", {})) for n in ("shino", "ranger", "vivi", "small")}
    ok = all(h.values())
    c.check(s, "each wears a spring skirt (its chains' ends found)", ok, f"{h}")
    if not ok:
        return
    c.check(s, "Shino scaled keeps her hem's place on the thigh", abs(h["ranger"][0] - h["shino"][0]) < 0.003, f"ranger {h['ranger'][0]:.4f}, shino {h['shino'][0]:.4f}")
    c.check(s, "Shino scaled keeps her hem's width", abs(h["ranger"][1] - h["shino"][1]) < 0.01, f"ranger {h['ranger'][1]:.4f}, shino {h['shino'][1]:.4f}")
    c.check(s, "Vivi scaled keeps her hem's width", abs(h["small"][1] - h["vivi"][1]) < 0.01, f"small {h['small'][1]:.4f}, vivi {h['vivi'][1]:.4f}")


def seated_outfits(run):
    """Residents beside whom the scene can sit, by their line's outer garment: skirted (a smock
    or an apron, `Skirt` spring chains) and coated (a coat; `Coat` chains once the generator
    builds them, docs/seat-contact/)."""
    book = json.load(open(LOOK_BOOK)) if os.path.exists(LOOK_BOOK) else {"lines": {}}
    rows = look_rows(run)
    out = {"skirt": [], "coat": []}
    for cid in residents(run, 400):
        outfit = (book["lines"].get(rows.get(cid, ""), {}).get("person") or {}).get("styles", {}).get("outfit", [])
        if any(p.startswith(("smock_", "apron_")) and not p.startswith("smock_bands") for p in outfit):
            out["skirt"].append(cid)
        elif any(p.startswith("coat-") for p in outfit):
            out["coat"].append(cid)
    return out


CLIP_VARIANTS = os.path.join(ROOT, "living/game/assets/characters/clip_variants.json")


def seat_clips(run, ids):
    """{resident: the animation its seated loop should play}: anim.rs `variants` over its look
    line's type and pieces (clip_variants.json; sit-f-select, the female ground sit)."""
    book = json.load(open(LOOK_BOOK)) if os.path.exists(LOOK_BOOK) else {"lines": {}}
    rows = look_rows(run)
    families = json.load(open(CLIP_VARIANTS))["families"]
    out = {}
    for cid in ids:
        person = book["lines"].get(rows.get(cid, ""), {}).get("person") or {}
        kind, worn = person.get("type", ""), person.get("styles", {}).get("outfit", [])
        out[cid] = next((f["clips"]["sit_ground"] for f in families if any(kind.startswith(t) for t in f["types"]) and all(w in worn for w in f["wears"])), "sit_ground")
    return out


def seat_segments(path, cid):
    """A sitter's ground one-shots from the feet log, each from its start to the next one: the
    peak speed of its hips and feet from its root (m/s) over the crossfade in (0.12 s) and after
    it, frames where the root moves (a placement) left out, and its hips' mean height over the
    ground in the seated loop. A pop between the variant clips would show as a peak above the
    originals' (`LIVING_GAME_CLIP_VARIANTS=0`) in the same segment."""
    if not os.path.exists(path):
        return None
    rows = feet_rows(path, cid)
    rel = lambda r, k: [a - b for a, b in zip(r[k][:3], r["root"])]
    out, cur, seated = [], None, []
    for a, b in zip(rows, rows[1:]):
        act = tuple(b["action"]) if b.get("action") else None
        if cur is None or act != cur["act"]:
            cur = {"act": act, "t0": b["t"], "fade_mps": 0.0, "after_mps": 0.0, "frames": 0}
            out.append(cur)
        dt = b["t"] - a["t"]
        if dt <= 0 or math.dist(a["root"], b["root"]) > 0.01:
            continue
        v = max(math.dist(rel(a, k), rel(b, k)) / dt for k in ("hips_at", "l", "r"))
        key = "fade_mps" if b["t"] - cur["t0"] < 0.12 else "after_mps"
        cur[key] = round(max(cur[key], v), 3)
        cur["frames"] += 1
        if b.get("clip") == "sit_ground":
            seated.append(b["hips_at"][1] - b["l"][3])
    segs = [dict(s, clip=s["act"][0], t0=round(s["t0"], 3), act=None) for s in out if s["act"] and s["act"][0] in ("sit_ground_down", "stand_up_ground")]
    return {"segments": [{k: v for k, v in x.items() if k != "act"} for x in segs], "seated_hips_over_ground_m": round(sum(seated) / len(seated), 4) if seated else None}


def script_t(text, step):
    """The client's clock (s) at the first live-script line for STEP (`live script: STEP (me …,
    t X s)`), the clock the feet log's `t` uses."""
    m = re.search(rf"live script: {re.escape(step)} \(me .*?, t ([\d.]+) s\)", text)
    return float(m.group(1)) if m else None


def feet_rows(path, cid):
    """A feet log's frames of one body (a line cut short when the client stopped is skipped)."""
    out = []
    for line in open(path):
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if r.get("id") == cid and r.get("hips_at"):
            out.append(r)
    return out


def seated_frames(path, cid, t0, t1):
    """The watched sitter's feet-log frames between t0 and t1 (client s) that show it off the
    seated loop: any one-shot over it (getting up, settling down again, a turn take) or its hips
    more than SEATED_HIPS_M over the ground (the seated loop keeps them about 0.11 m up, standing
    about 0.9). Returns (frames in the window, [(t, clip, action, hips over ground m)])."""
    if not os.path.exists(path) or t0 is None or t1 is None:
        return 0, []
    rows = [r for r in feet_rows(path, cid) if t0 <= r["t"] <= t1]
    off = [(round(r["t"], 3), r.get("clip"), (r.get("action") or [None])[0], round(r["hips_at"][1] - r["l"][3], 3))
           for r in rows if r.get("action") or r["hips_at"][1] - r["l"][3] > SEATED_HIPS_M]
    return len(rows), off


SEATED_HIPS_M = 0.35


@scenario("seat")
def seat(run, c):
    """Seated cloth on the ground (seat-2a, docs/seat-contact/): skirted and coated residents
    beside me in the crowded street (eight near: me and seven), told to rest at noon in dry
    weather (`set_behavior` `{"do": "rest"}`, scene setup), so town.rs sits them on the ground
    (`sit_ground_down`, then `sit_ground`; about three in ten stand at ease instead), then told to
    go home at `sync:up`, so they get up where they sat (`stand_up_ground`) and walk off.
    Stills going down, seated, getting up and up. They sit about 18 s, across two of the
    authority's 8 s rest renewals (a new `doing` row each, snapshotted at `held0` and `held1`),
    and meanwhile the camera goes Far, Near, Far and Near, so their springs rest and wake (the
    re-entry reseed, `LIVING_GAME_PERF=springwake`). Nobody seated may rise before `up`: the
    watched sitter's feet log stays in the seated loop (no one-shot, hips low) from the seated
    dump to `up`, every sitter's one `gets up` line comes after `up`, and every seated wake starts
    where its chains were drawn (under 5° at waking) and does not swing (under 10° a frame). Two arms: the contact on, and off
    (`LIVING_GAME_SEAT_CONTACT=0`); `LIVING_GAME_PERF=seat` logs each seated character's lowest
    cloth tail above its ground, and frames.csv and the springs line give the cost. Each sitter's
    `seat:` line names the animation its seated loop plays: the female ground sit's variant for an
    adult line in `trousers-f` and `boots-f`, else the original (sit-f-select)."""
    s = "seat"
    who = seated_outfits(run)
    want = seat_clips(run, who["skirt"] + who["coat"])
    skirts = who["skirt"][:4]
    # At least one sitter of each kind, so the selector is seen both ways.
    for kind in (lambda i: want[i] != "sit_ground", lambda i: want[i] == "sit_ground"):
        if skirts and not any(kind(i) for i in skirts + who["coat"][:3]):
            extra = next((i for i in who["skirt"][4:] if kind(i)), None)
            if extra is not None:
                skirts = skirts[:3] + [extra] if len(skirts) == 4 else skirts + [extra]
    ids = skirts + who["coat"][:3]
    c.check(s, "skirted and coated residents to seat", len(who["skirt"]) >= 1 and len(who["coat"]) >= 1 and len(ids) == 7, f"skirt {who['skirt'][:4]}, coat {who['coat'][:3]}")
    if len(ids) < 2:
        return
    ring = [(2.2, 0.0), (-2.2, 0.0), (0.0, 2.2), (0.0, -2.2), (1.6, 1.6), (-1.6, -1.6), (1.6, -1.6)]
    free = [f"{i}:{x}:{y}" for i, (x, y) in zip(ids, ring)]
    rest = json.dumps(json.dumps({"do": "rest"}))
    home = json.dumps(json.dumps({"do": "goto", "target": "home"}))
    doing = "sql|SELECT id, since_ms, until_ms FROM doing WHERE " + " OR ".join(f"id = {i}" for i in ids)
    syncs = ['setup=set_world_law|"fov_on"|"false";place_at|{me}|420.5|255.5;set_weather|false|900',
             "noon=sql|UPDATE world SET epoch_ms = {epoch_at:12} WHERE id = 0",
             "sit=" + ";".join(f"set_behavior|{i}|{rest}" for i in ids),
             "held0=" + doing, "held1=" + doing,
             "up=" + ";".join(f"set_behavior|{i}|{home}" for i in ids)]
    # Seated from about 4 s after `sit` to `up` about 18 s after it: across the rest renewals at
    # about 8 and 16 s (the first while the camera is Near between two Far stops), and a
    # Far → Near → Far → Near zoom.
    plan = ("ready;sync:noon;sync:setup;wait:2;sync:scene;look:180;cursor:0.5,0.55;wait:3;notches:30;wait:2;dump:standing;shot:00_standing;"
            "sync:sit;wait:1.6;shot:01_down;wait:2.4;dump:seated;shot:02_seated;sync:held0;"
            "notches:-30;wait:2;notches:30;wait:2.5;shot:03_idle;notches:-30;wait:2;notches:30;wait:3;dump:rewoken;shot:04_rewoken;"
            "wait:5;dump:renewed;shot:04b_renewed;sync:held1;"
            "sync:up;wait:0.9;shot:05_rising;wait:1.2;shot:06_rising_late;wait:2;dump:up;shot:07_up;wait:1;quit")
    arms = {}
    # One variant sitter's hips and feet, frame by frame (the feet log): its seat's height, and
    # each ground one-shot's peak speed, to compare with the originals' (seat_segments).
    watch = next((i for i in ids if want.get(i) != "sit_ground"), None)
    for arm, env in (("on", {}), ("off", {"LIVING_GAME_SEAT_CONTACT": "0"})):
        name = f"{s}-{arm}"
        ev = os.path.join(ROOT, ".local/living/verify", run, "ui", name)
        os.makedirs(ev, exist_ok=True)
        frames = os.path.join(ev, "frames.csv")
        feet = os.path.join(ev, "feet.jsonl")
        if arm == "on" and watch is not None:
            env = dict(env, LIVING_GAME_FEET=feet, LIVING_GAME_FEET_ID=str(watch))
        out, code, text = drive(run, name, plan, free=free, syncs=syncs, env=dict(env, LIVING_GAME_PERF="seat,springwake", LIVING_GAME_FRAMES=frames, LIVING_GAME_FPS_CAP="0"))
        c.check(s, f"{arm}: client ran and joined", code == 0, text[-300:])
        L = log(out)
        up, after_up = next_sync_wait(L, 0, {os.path.join(out, "up.go"): "up"})
        sat = sorted({int(m) for m in re.findall(r"seat: #(\d+) sits on the ground", L[:after_up])} & set(ids))
        plays = {int(i): clip for i, clip in re.findall(r"seat: #(\d+) sits on the ground .*?, plays (\S+)", L)}
        rose = sorted({int(m) for m in re.findall(r"seat: #(\d+) is off the ground", L[after_up:])} & set(ids))
        # A sitter whose body left sight while it got up (the authority walks it off at once and
        # stops sending it past sight, ~11 m, before its drawn rise ends): its seat went with its
        # fading body (live.rs `leaves sight`). Accounted for, and named apart.
        left = {int(i): float(d) for i, d in re.findall(r"seat: #(\d+) leaves sight getting up, (-?[\d.]+|NaN) m from me", L[after_up:]) if int(i) in ids and d != "NaN"}
        seated_left = sorted({int(i) for i in re.findall(r"seat: #(\d+) leaves sight seated", L[:after_up])} & set(ids))
        lows = [(n, int(k), float(v)) for n, k, v in re.findall(r"seat: (.+?) \S+: (\d+) cloth joints, lowest tail (-?[\d.]+|inf) mm", L) if v != "inf"]
        # The seated characters' springs waking as the camera comes back near (their entities, from
        # their seat reports), after they sat.
        seated_e = {e for _, e, k, _ in re.findall(r"seat: (.+?) (\S+): (\d+) cloth joints, lowest tail (-?[\d.]+|inf) mm", L) if int(k) > 0}
        # Seated: from the seated dump to the `up` request.
        seated_log = L.split("live script: dump:seated", 1)[-1].split("live script: sync:up (", 1)[0]
        wakes = [(e, float(a), float(b)) for e, a, b in re.findall(r"springwake: \S+ (\S+) \(\d+ joints, settle \d+\): largest turn ([\d.]+)° at waking, ([\d.]+)° a frame after", seated_log) if e in seated_e]
        # The authority's rest rows while they sat: a renewal extends the row in place (doing-renew:
        # the same `since_ms`, a later `until_ms`), or, on older modules, writes a new `since_ms`.
        sc = json.load(open(os.path.join(out, "scene.json"))) if os.path.exists(os.path.join(out, "scene.json")) else {}
        held = [{r["id"]: (r["since_ms"], r["until_ms"]) for r in ((sc.get("snaps") or {}).get(k) or [{}])[0].get("rows", [])} for k in ("held0", "held1")]
        renewed = sorted(i for i in sat if i in held[0] and i in held[1] and (held[0][i][0] != held[1][i][0] or held[1][i][1] > held[0][i][1]))
        # Getting up after `sit` (residents resting already when the scene places them get up then).
        sit_at = L.find("live script: sync:sit (")
        gets_up = [(int(i), m.start()) for m in re.finditer(r"seat: #(\d+) gets up", L) for i in [m.group(1)] if int(i) in ids and m.start() > sit_at >= 0]
        early_up = sorted({i for i, at in gets_up if at < after_up})
        t_seated, t_far1, t_up = script_t(L, "dump:seated"), script_t(L, "notches:-30"), script_t(L, "sync:up")
        t_far2 = next((float(x) for x in re.findall(r"live script: notches:-30 \(me .*?, t ([\d.]+) s\)", L)[1:2]), None)
        springs = [float(x) for x in re.findall(r"springs: .*?([\d.]+) µs CPU a character-step", L)]
        rows = []
        if os.path.exists(frames):
            rows = [tuple(map(int, line.split(","))) for line in open(frames) if line.strip()]
        ms = sorted(r[1] / 1000 for r in rows[len(rows) // 4:])
        arms[arm] = {"sat": sat, "rose": rose, "left_sight_getting_up": left, "left_sight_seated": seated_left, "cloth_lows_mm": lows, "wakes_deg": wakes, "spring_us_per_char_step": springs,
                     "frames": len(ms), "p50_ms": ms[len(ms) // 2] if ms else None, "p99_ms": ms[math.ceil(len(ms) * .99) - 1] if ms else None,
                     "skirt": [i for i in sat if i in who["skirt"]], "coat": [i for i in sat if i in who["coat"]],
                     "plays": {i: plays.get(i) for i in sat}, "selected": {i: want.get(i) for i in sat}}
        if arm == "on" and watch is not None:
            arms[arm]["segments"] = seat_segments(feet, watch)
            c.check(s, f"on: #{watch}'s sitting down, seated loop and getting up are in its feet log (seat.json `segments`)",
                    bool(arms[arm]["segments"] and arms[arm]["segments"]["segments"] and arms[arm]["segments"]["seated_hips_over_ground_m"]), json.dumps(arms[arm]["segments"])[:600])
        d = dump(out, "seated") or {}
        seen = {x["id"] for x in d.get("seen") or []}
        c.check(s, f"{arm}: a skirted and a coated resident sit on the ground in view", arms[arm]["skirt"] and arms[arm]["coat"] and set(sat) <= seen, f"sat {sat} (skirt {arms[arm]['skirt']}, coat {arms[arm]['coat']}); in view {sorted(seen)}")
        c.check(s, f"{arm}: everyone who sat got up and was let go of the ground after up (or left sight getting up, its seat with it)", up == "up" and sat and sorted(set(rose) | set(left)) == sat and not seated_left and len(rose) >= 1,
                f"sat {sat}, off the ground {rose}, left sight getting up {left} (m from me), left sight seated {seated_left}")
        variant = [i for i in sat if want.get(i) != "sit_ground"]
        c.check(s, f"{arm}: each sitter plays the seated loop its line selects (a variant for {len(variant)}, the original for {len(sat) - len(variant)})",
                sat and variant and len(variant) < len(sat) and all(plays.get(i) == want.get(i) for i in sat), f"plays {arms[arm]['plays']}, selected {arms[arm]['selected']}")
        if arm == "on":
            cloth = [x for x in lows if x[1] > 0]
            c.check(s, "on: seated cloth tails stay on the ground's side (at most 5 mm under it)", cloth and min(v for _, _, v in cloth) >= -5.0, f"{len(cloth)} reports; lowest {min((v for _, _, v in cloth), default=None)} mm")
        c.check(s, f"{arm}: the authority renewed the sitters' rest while they sat (its doing row extended or new between held0 and held1)", renewed, f"held0 {held[0]}, held1 {held[1]}")
        if watch is not None and arm == "on":
            n, off = seated_frames(feet, watch, t_seated, t_up)
            arms[arm]["seated_off_loop"] = off[:40]
            c.check(s, f"on: #{watch} stays seated across the rest renewal (no one-shot, hips under {SEATED_HIPS_M} m, seated dump to up)",
                    n > 100 and watch in renewed and not off, f"{n} frames; renewed {renewed}; off the loop {off[:6]}")
            n2, off2 = seated_frames(feet, watch, t_far1, (t_far2 or 0) + 2.0)
            c.check(s, f"on: #{watch} stays seated across Far → Near → Far", n2 > 50 and t_far2 and not off2, f"{n2} frames, t {t_far1}–{t_far2}; off the loop {off2[:6]}")
        arms[arm]["gets_up"] = [i for i, _ in gets_up]
        c.check(s, f"{arm}: every sitter gets up once, after up (`seat: #ID gets up`), none while seated", sat and early_up == [] and sorted(i for i, _ in gets_up) == sat,
                f"gets up {[i for i, _ in gets_up]} (before up {early_up}), sat {sat}")
        c.check(s, f"{arm}: seated springs wake (Far → Near) where they were drawn (under 5° at waking) and settle without a swing (under 10° a frame)",
                wakes and max(a for _, a, _ in wakes) < 5.0 and max(b for _, _, b in wakes) < 10.0, f"{wakes}")
    evidence = os.path.join(ROOT, ".local/living/verify", run, "ui", "seat.json")
    json.dump(arms, open(evidence, "w"), indent=1)
    on, off = arms.get("on", {}), arms.get("off", {})
    c.check(s, "frame cost with the contact on and off (eight near, crowded street)", on.get("p50_ms") and off.get("p50_ms"), json.dumps({k: {x: arms[k].get(x) for x in ("frames", "p50_ms", "p99_ms")} for k in arms}))

FAKE_LLM = os.path.join(ROOT, ".agents/skills/verify-llm/scripts/fake_llm.py")


def saying_ms(text):
    """`living_rules::saying::saying_ms`: 330 ms a word, 1.5 s at least, 8 s at most."""
    return min(max(len(text.split()) * 330, 1500), 8000)


def free_port():
    import socket
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@scenario("reply-pace")
def reply_pace(run, c):
    """A resident's reply bubble at speaking pace (reply-pace, docs/COMMUNICATION.md §21). Since
    reply-timing a mind says a reply as soon as it is ready, so its `at_ms` can fall inside the
    time the answered line takes to say. The client shows the reply's bubble once that line is
    done being said (its `at_ms` plus `saying_ms`, 330 ms a word, at least 1.5 s), and the
    answered line's bubble ends then: one bubble an exchange.

    A real mind service (`living-mind`, LIVING_ONLY the one resident) answers through a local fake
    model (verify-llm's fake_llm.py; no paid call). At noon on open grass (UNHEARD_SPOT, anyone
    within 25 m put away), resident A is held 2 m west of a fresh player.
    1. Near: the player says a twelve-word line to A; the fake answers at once. The reply's row
       comes well within the line's saying time; the client log's `bubble:` line gives when its
       bubble first showed. Dumps every 0.2 s: never my bubble and A's at once.
    2. Out of range: the player says a second line and walks east for 4 s; the fake answers after
       5 s, when the player is beyond a said line's reach (9 m) and within a call's. A's reply
       gets the authority's `silence` ("… could not have heard you."), A's mind takes its one
       follow-up turn with those words ("# What came of your last words"), and the fake calls
       out 4 s later. The player meanwhile walks back west for 2 s, into sight (11 m by day) and
       within the call's reach: the call shows as said (its bubble not held by A's paced
       reply before it) and in the Log."""
    s = "reply-pace"
    a = residents(run, 1)[0]
    names = {r["id"]: r["name"] for r in sql(run, f"SELECT id, name FROM character WHERE id = {a}")}
    cards = {r["name"]: r["carry_m"] for r in sql(run, "SELECT name, carry_m FROM speech_card")}
    ui = os.path.join(ROOT, ".local/living/verify", run, "ui")
    ev = os.path.join(ui, s)
    os.makedirs(ev, exist_ok=True)
    near_line = "Good morning to you, how is the bread at the bakery today? (rp-near)"
    far_line = "And what about the honey cakes, are there any left? (rp-far)"
    follow_head = "# What came of your last words"
    follow_say = "Did you hear me? The cakes are gone."
    script = {"replies": {"think": {"thought": "I listen.", "intend": ["wait"], "say": None},
                          "deliberate": {"graph": {"wait": 300}, "weight": 1.5, "plan": "verify-ui wait"},
                          "talk": {"thought": "Nothing more.", "say": "", "to": 0, "acts": [], "end": True, "settled": None}},
              "rules": [
                  # The follow-up turn first: its prompt carries both lines of the exchange too.
                  {"purpose": "talk", "contains": follow_head, "times": -1,
                   "delay_s": 4, "reply": {"thought": "They did not hear me.", "say": follow_say, "way": "call", "to": 0, "acts": [], "end": True, "settled": None}},
                  {"purpose": "talk", "contains": "rp-far", "times": -1, "delay_s": 5,
                   "reply": {"thought": "Cakes.", "say": "None left, sorry.", "to": 0, "acts": [], "end": False, "settled": None}},
                  {"purpose": "talk", "contains": "rp-near", "times": -1,
                   "reply": {"thought": "A greeting.", "say": "Fresh as ever, come and see.", "to": 0, "acts": [], "end": False, "settled": None}},
              ]}
    script_path = os.path.join(ev, "fake-script.json")
    json.dump(script, open(script_path, "w"), indent=1)
    requests = os.path.join(ev, "fake-requests.jsonl")
    port = free_port()
    target = os.environ.get("CARGO_TARGET_DIR") or os.path.join(ROOT, ".local/target")
    mind_bin = os.path.join(target, "release/living-mind")
    if not os.path.exists(mind_bin):
        c.check(s, "the mind binary is built in CARGO_TARGET_DIR", False, mind_bin)
        return
    models = {"default": "local", "profiles": {"local": {"base_url": f"http://127.0.0.1:{port}/v1", "model": "fake-ui", "key_env": "LIVING_VERIFY_FAKE_KEY",
                                                          "max_tokens": 256, "requests_per_minute": 6000, "reasoning_effort": {p: p for p in ("think", "deliberate", "consolidate", "talk")}}}}
    models_path = os.path.join(ev, "models.json")
    json.dump(models, open(models_path, "w"), indent=1)
    st = verify.load(run)
    procs = []
    fake_log = open(os.path.join(ev, "fake-server.log"), "a")
    mind_log = open(os.path.join(ev, "mind.log"), "a")
    try:
        fake = subprocess.Popen([sys.executable, FAKE_LLM, "--port", str(port), "--log", requests, "--script", script_path], cwd=ROOT, stdout=fake_log, stderr=subprocess.STDOUT)
        procs.append(fake)
        deadline = time.time() + 10
        while time.time() < deadline and "READY " not in open(os.path.join(ev, "fake-server.log")).read():
            time.sleep(0.2)
        # The fake answers before the mind starts (a first connection once timed out).
        import urllib.request
        for attempt in range(20):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as r:
                    if r.status == 200:
                        break
            except OSError:
                time.sleep(0.5)
        else:
            c.check(s, "the fake model answers its health check", False, f"port {port}")
            return
        env = dict(os.environ, LIVING_ROOT=ROOT, LIVING_SERVER=os.environ.get("LIVING_STDB_URL", "http://127.0.0.1:3300"), LIVING_DB=st["db"], LIVING_RUN=st["db"],
                   LIVING_SEED="island", LIVING_MODELS=models_path, LIVING_NEO4J="off", LIVING_NEO4J_PASSWORD="", LIVING_ONLY=str(a),
                   LIVING_LLM_PER_MIN="0", LIVING_CONCURRENCY="4", LIVING_TOKEN=verify.admin_token(), LIVING_VERIFY_FAKE_KEY="dummy-local-only",
                   LIVING_LOD="0", NO_PROXY="127.0.0.1,localhost", RUST_LOG="info,neo4rs=warn,spacetimedb_sdk=warn")
        mind = subprocess.Popen([mind_bin], cwd=ROOT, env=env, stdout=mind_log, stderr=subprocess.STDOUT)
        procs.append(mind)
        json.dump({"fake_pid": fake.pid, "mind_pid": mind.pid, "only": [a], "port": port}, open(os.path.join(ev, "processes.json"), "w"))
        deadline = time.time() + 60
        while time.time() < deadline and "world subscribed:" not in open(os.path.join(ev, "mind.log"), errors="replace").read():
            if mind.poll() is not None:
                break
            time.sleep(0.5)
        c.check(s, "the mind service minds the resident through the fake model", mind.poll() is None and "world subscribed:" in open(os.path.join(ev, "mind.log"), errors="replace").read(), "see mind.log")
        people = {r["id"] for r in sql(run, "SELECT id, kind FROM character WHERE kind = 'person'")}
        ax, ay = UNHEARD_SPOT
        near0 = [r for r in sql(run, "SELECT id, x, y FROM body") if r["id"] in people and r["id"] != a and ((r["x"] - ax) ** 2 + (r["y"] - ay) ** 2) ** 0.5 < 25]
        clear = ";".join(f"place_at|{r['id']}|{ax + 40}|{ay + 3 * i}" for i, r in enumerate(near0)) or "sql|SELECT id FROM world"
        dumps = lambda p, n: "".join(f"wait:0.2;dump:{p}{k:02d};" for k in range(n))
        plan = ("ready;sync:noon;sync:clear;sync:spot;wait:2;sync:scene;wait:3;"
                "point:{A};wait:0.5;key:Enter:tap;wait:0.6;dump:n0;type:" + near_line + ";enter;" + dumps("n", 30) + "shot:01_near;wait:3;"
                "point:{A};wait:0.5;key:Enter:tap;wait:0.6;type:" + far_line + ";enter;wait:0.3;cursor:;walk:90:4;sync:walked;wait:1.5;walk:270:2;sync:back;" + dumps("f", 40) + "shot:02_follow;wait:2;"
                "key:KeyL:tap;wait:0.6;dump:log;shot:03_log;quit").replace("{A}", str(a))
        syncs = ["noon=sql|UPDATE world SET epoch_ms = {epoch_at:12} WHERE id = 0", f"clear={clear}", f"spot=place_at|{{me}}|{ax}|{ay}",
                 f"walked=sql|SELECT id, x, y FROM body WHERE id = {{me}} OR id = {a}", f"back=sql|SELECT id, x, y FROM body WHERE id = {{me}} OR id = {a}"]
        tok = os.path.join(ui, f"reply-pace-{int(time.time())}.token")
        out, code, text = drive(run, s, plan, places=[f"{a}:-2:0"], syncs=syncs, extra=["--token", tok, "--player", "Asker"])
        time.sleep(2)
    finally:
        stops = []
        for p in reversed(procs):
            if p.poll() is None:
                p.terminate()
                try:
                    p.wait(timeout=8)
                    stops.append((p.pid, "SIGTERM"))
                except subprocess.TimeoutExpired:
                    p.kill()
                    p.wait(timeout=5)
                    stops.append((p.pid, "SIGKILL"))
            else:
                stops.append((p.pid, f"exited {p.returncode}"))
        json.dump(stops, open(os.path.join(ev, "stops.json"), "w"))
        fake_log.close()
        mind_log.close()
        # The resident back to the admin's default (no mind): a still graph, as --place left it.
        call_admin(run, "set_behavior", [a, json.dumps({"wait": 600})])
    c.check(s, "client ran and joined (a fresh player)", code == 0, text[-300:])
    sc = json.load(open(os.path.join(out, "scene.json"))) if os.path.exists(os.path.join(out, "scene.json")) else {}
    me = sc.get("me")
    L = log(out)
    rows = sql(run, f"SELECT id, observer, kind, subject, object, at_ms, text FROM experience WHERE (observer = {me} OR observer = {a}) AND (kind = 'said' OR kind = 'speech' OR kind = 'silence')") if me else []
    rows.sort(key=lambda r: r["at_ms"])
    said = lambda words: next((r for r in rows if r["observer"] == me and r["kind"] == "said" and words in r["text"]), None)
    heard = lambda words: next((r for r in rows if r["observer"] == me and r["kind"] == "speech" and r["subject"] == a and words in r["text"]), None)
    shown = {}
    for m in re.finditer(r'bubble: #(\d+) to #(\d+) shown at (\d+) ms, said at (\d+) ms(?:, paced to (\d+) ms after #(\d+)\'s line said at (\d+) ms and shown at (\d+) ms \((\d+) ms to say\))?: "(.*)"', L):
        shown[m[10]] = {"speaker": int(m[1]), "to": int(m[2]), "shown": int(m[3]), "at": int(m[4]), "paced": int(m[5]) if m[5] else None, "after": int(m[7]) if m[7] else None}
    ended = [(int(t), int(e)) for t, e in re.findall(r"bubble: my line \(sent at (\d+) ms\) ended at (\d+) ms", L)]
    # 1. Near.
    mine1, reply1 = said(near_line), heard("Fresh as ever")
    need = saying_ms(near_line)
    b1 = shown.get("Fresh as ever, come and see.")
    result = {"me": me, "a": a, "cards": cards, "near_line_ms_to_say": need}
    if mine1 and reply1:
        result["near"] = {"said_at": mine1["at_ms"], "reply_at": reply1["at_ms"], "reply_after_ms": reply1["at_ms"] - mine1["at_ms"],
                          "bubble_shown": b1 and b1["shown"], "bubble_after_ms": b1 and b1["shown"] - mine1["at_ms"]}
    c.check(s, "near: the reply was said within the line's saying time (said when ready)", mine1 and reply1 and 0 < reply1["at_ms"] - mine1["at_ms"] < need, json.dumps(result.get("near")))
    c.check(s, "near: the reply's bubble first shows at least the line's saying time after it was said", b1 and mine1 and b1["shown"] - mine1["at_ms"] >= need and b1["paced"] == mine1["at_ms"] + need, f"{b1}; said {mine1 and mine1['at_ms']}; to say {need} ms")
    c.check(s, "near: and not much later (within 0.5 s of its paced time)", b1 and b1["paced"] and b1["shown"] - b1["paced"] < 500, str(b1))
    seq = []
    for k in ["n0"] + [f"n{i:02d}" for i in range(30)]:
        bs = {x.get("speaker") for x in (dump(out, k) or {}).get("bubbles") or []}
        seq.append(("me" if me in bs else "") + ("A" if a in bs else ""))
    c.check(s, "near: my bubble, then A's in its place, never both at once (dumps every 0.2 s)", "meA" not in seq and "me" in seq and "A" in seq and seq.index("A") > seq.index("me") and "me" not in seq[seq.index("A"):], " ".join(x or "-" for x in seq))
    c.check(s, "near: my bubble ended in the frame the reply's showed", b1 and any(e <= b1["shown"] and e >= b1["paced"] for _, e in ended), f"ended {ended}; reply {b1}")
    # 2. Out of range.
    mine2 = said(far_line)
    silences = [r for r in rows if r["observer"] == a and r["kind"] == "silence" and r["subject"] == me and mine2 and r["at_ms"] > mine2["at_ms"]]
    reqs = [json.loads(l) for l in open(requests)] if os.path.exists(requests) else []
    text_of = lambda e: "\n".join(str(x.get("content", "")) for x in (e.get("body") or {}).get("messages", []))
    follow = [text_of(e) for e in reqs if e.get("purpose") == "talk" and follow_head in text_of(e)]
    walked = {r["id"]: (r["x"], r["y"]) for r in (((sc.get("snaps") or {}).get("walked") or [{}])[0].get("rows") or [])}
    gap = math.dist(walked[me], walked[a]) if me in walked and a in walked else None
    result["far"] = {"apart_m": gap, "silences": [r["text"] for r in silences], "follow_prompts": len(follow)}
    c.check(s, "far: the player walked beyond a said line's reach, within a call's", gap is not None and cards.get("say", 9) < gap < cards.get("call", 0), f"{gap} m; cards {cards}")
    c.check(s, "far: A's reply met the authority's silence (… could not have heard you)", silences and "could not have heard you" in silences[0]["text"], str(silences))
    c.check(s, "far: A's one follow-up turn weighs those words", len(follow) == 1 and silences and follow[0].rstrip().endswith(f"{follow_head}\n{silences[0]['text']}"), f"{len(follow)} follow-up prompts")
    f1, b2 = heard(follow_say), shown.get(follow_say)
    fs = [{x.get("speaker") for x in (dump(out, f"f{i:02d}") or {}).get("bubbles") or []} for i in range(40)]
    back = {r["id"]: (r["x"], r["y"]) for r in (((sc.get("snaps") or {}).get("back") or [{}])[0].get("rows") or [])}
    back_m = math.dist(back[me], back[a]) if me in back and a in back else None
    result["far"]["back_m"] = back_m
    c.check(s, "far: the follow-up call reaches the player, back in sight, unpaced, and its bubble shows", f1 and b2 and b2["speaker"] == a and b2["shown"] - f1["at_ms"] < 500 and any(a in x for x in fs), f"row {f1 and f1['text']}; bubble {b2}; back {back_m} m; dumps with A {sum(a in x for x in fs)}")
    logl = [x.get("text") or "" for x in (((dump(out, "log") or {}).get("extra") or {}).get("lines") or [])]
    c.check(s, "far: the Log has the follow-up too", any(follow_say in t for t in logl), str(logl[-6:]))
    at = lambda w: next((i for i, t in enumerate(logl) if w in t), None)
    c.check(s, "the Log keeps every line unpaced, in the order said (my line, then the reply)", None not in (at(near_line), at("Fresh as ever")) and at(near_line) < at("Fresh as ever") < at(far_line), str(logl))
    result["follow"] = {"row": f1, "bubble": b2}
    json.dump(result, open(os.path.join(ev, "reply-pace.json"), "w"), indent=1)
    print(f"{s}: {json.dumps(result)}", flush=True)


# ---- heed for players (docs/ATTENTION_BUDGET.md "Built: the player side"; features/heed.md) ----

HEED_LAWS = ("heed_on", "heed_players", "heed_ceiling")
HEED_MAX = "You can keep at most 4 others pinned at once."
HEED_UNSEEN = "You can only keep track of someone you can see now."
HEED_EMPTY = "There is no one in the throng there to pick out."


@contextmanager
def heed_fixture(run):
    """Heed laws back to the world's own values (else shipped defaults) when the scene ends."""
    original = own_laws(lambda q: sql(run, q))
    try:
        yield
    finally:
        for law in HEED_LAWS:
            default = "16" if law == "heed_ceiling" else "false"
            call_admin(run, "set_world_law", [law, original.get(law, shipped_law(law) or default)], check=True)


def heed_on_calls():
    return [("set_world_law", ["heed_on", "true"]), ("set_world_law", ["heed_players", "true"])]


def staged_drive(run, name, plan, handlers, extra=(), env=None, timeout=900):
    """drive.py with this scenario's own syncs: at each `sync:NAME` the client waits for, the
    handler `handlers[NAME](me, ident)` runs (admin calls, owner SQL snapshots), then the client
    goes on. Returns (out, exit code, drive log, the handlers' results by name)."""
    name = f"{name}-{THEME}" if THEME else name
    base = os.path.join(ROOT, ".local/living/verify", run, "ui")
    out = os.path.join(base, name)
    os.makedirs(base, exist_ok=True)
    fresh_log(out)
    cmd = [sys.executable, os.path.join(HERE, "drive.py"), "--run", run, "--name", name, "--plan", plan, "--timeout", str(timeout)] + list(extra)
    drive_log_path = os.path.join(base, f"{name}.drive.log")
    p = subprocess.Popen(cmd, stdout=open(drive_log_path, "w"), stderr=subprocess.STDOUT, env=dict(os.environ, **env) if env else None)
    results, done = {}, set()
    try:
        while p.poll() is None:
            text = log(out)
            m = re.search(r"playing character #(\d+)", text)
            me = int(m.group(1)) if m else None
            for w in re.finditer(r"live script: waiting for (\S+)/([\w-]+)\.go", text):
                sync = w.group(2)
                if sync in done or sync not in handlers:
                    continue
                done.add(sync)
                try:
                    results[sync] = handlers[sync](me, identity_of(out))
                except Exception as e:  # recorded, and the client goes on
                    results[sync] = {"error": repr(e)}
                open(os.path.join(out, f"{sync}.go"), "w").close()
            time.sleep(0.2)
    finally:
        if p.poll() is None:
            p.terminate()
        p.wait()
    verify.require_running(verify.load(run), verify.admin_token())
    json.dump(results, open(os.path.join(out, "syncs.json"), "w"), indent=1, default=str)
    return out, p.returncode, open(drive_log_path, errors="replace").read(), results


def verify_sql_noon(run):
    """The world's epoch set so it is noon now (owner SQL through verify.py, which records the
    epoch for cleanup), as drive.py's `{epoch_at:12}`."""
    from drive import epoch_at
    q = f"UPDATE world SET epoch_ms = {epoch_at(run, 12.0)} WHERE id = 0"
    sql(run, q, check=True)
    return q


CLOTH_COLS = (
    "cloth_yellow", "cloth_black", "cloth_green", "cloth_tan", "cloth_blue",
    "cloth_red", "cloth_cream", "cloth_navy", "cloth_purple", "cloth_grey",
)


def throng_rows(run, ident):
    """My throng as the authority holds it (owner SQL)."""
    cols = ("cell", "size", "count", "spread", "heading", "moving", "fighting", "kinds",
            "people", "wolves", "deer", "others", "centre_x", "centre_y") + CLOTH_COLS
    rows = owner_rows(run, f"SELECT {', '.join(cols)} FROM seen_throng WHERE viewer = 0x{ident}") or []
    return [{k: r[k] for k in cols} for r in rows]


def heed_choice(run, me):
    rows = owner_rows(run, f"SELECT actor, pins, focus, at_ms FROM heed_choice WHERE actor = {me}") or []
    if not rows:
        return None
    r = rows[0]
    f = r.get("focus")
    # An Option over SQL: {"some": n} or {"none": []}, or [0, n] / [1, []] by version.
    if isinstance(f, dict):
        f = f.get("some")
    elif isinstance(f, list):
        f = f[1] if f and f[0] == 0 else None
    return {"pins": list(r.get("pins") or []), "focus": f}


def perception_sets(text):
    """Each `perception: subscribing the … set (N queries; tables: …)` line: (N, tables)."""
    return re.findall(r"perception: subscribing the \w+ set \((\d+) queries; (tables: [^;)]*)", text)


def _expected_cloth_alloc(q, has_book):
    """Per-word card counts for square `q`'s person cards from its 10-word `cloths` histogram
    (mirrors `throng::tops_with`). Returns `(want_tinted, active_book_words)` where
    `active_book_words` is the number of distinct non-`grey` words allocated >= 1 card."""
    if not has_book:
        return 0, 0
    n_people = q.get("people", 0)
    cloths = q.get("cloths") or []
    if n_people == 0 or len(cloths) != 10:
        return 0, 0
    # Index 9 ("grey") has no outfit in the shipped look book, so it stays neutral.
    slots = [(idx, cnt) for idx, cnt in enumerate(cloths) if cnt > 0]
    total_c = sum(cnt for _, cnt in slots)
    if total_c == 0:
        return 0, 0
    if total_c <= n_people:
        alloc = [cnt for _, cnt in slots]
    else:
        # Proportional largest-remainder apportionment across active slots.
        exacts = [cnt * n_people / total_c for _, cnt in slots]
        floors = [int(math.floor(e)) for e in exacts]
        rem = n_people - sum(floors)
        order = sorted(range(len(slots)), key=lambda i: (-(exacts[i] - floors[i]), i))
        for i in order[:rem]:
            floors[i] += 1
        alloc = floors
    want_tinted = sum(alloc[i] for i, (idx, _) in enumerate(slots) if idx != 9)
    active_book = sum(1 for i, (idx, _) in enumerate(slots) if idx != 9 and alloc[i] > 0)
    return want_tinted, active_book


def squares_ok(t):
    """Each square of a dump's throng drawn as its row says: `count` cards, the poses by its
    shares, per-kind counts, cards tinted per its 10-word `cloths` histogram, centred on its
    centroid and inside the square."""
    bad = []
    has_book = (t or {}).get("tint") == "book"
    for q in (t or {}).get("squares") or []:
        n, f, m = q["count"], q["fighting"], q["moving"]
        want_f = min(f, n)
        want_w = min(m, n - want_f)
        side = max(1, q["size"]) * 6.0
        cx, cy = q["cell"]
        ox, oy = cx * 6.0, cy * 6.0
        ce = q.get("centre") or [0, 0]
        want_centroid = [ox + min(ce[0], side - 1.0) + 0.5, oy + min(ce[1], side - 1.0) + 0.5]
        cent = q.get("centroid") or [0.0, 0.0]
        cent_ok = abs(cent[0] - want_centroid[0]) < 1e-3 and abs(cent[1] - want_centroid[1]) < 1e-3
        mc = q.get("mean_card")
        reach = max(q["spread"] * 0.5, 0.55 * math.sqrt(max(n, 1)), 0.75) + 0.70
        mean_ok = True if n == 0 else (mc is not None and (math.hypot(mc[0] - cent[0], mc[1] - cent[1]) <= (0.70 if n == 1 else reach)))
        cloths = q.get("cloths") or []
        want_tinted, active_book = _expected_cloth_alloc(q, has_book)
        rgb_map = q.get("rgb") or {}
        rgb_sum = sum(rgb_map.values())
        if (q["cards"] != n or q["fight"] != want_f or q["walk"] != want_w or q["stand"] != n - want_f - want_w
                or not q["inside"] or len(cloths) != 10
                or q["tinted"] != want_tinted or rgb_sum != q["tinted"] or len(rgb_map) != active_book
                or not cent_ok or not mean_ok):
            bad.append(q)
    return bad


def rows_match(t, auth):
    """How many of the authority's rows the client holds alike (cell, size, count, moving,
    fighting, cloths), of how many."""
    mine = {((q["cell"][0] << 16) | q["cell"][1], q["size"], q["count"], q["moving"], q["fighting"], tuple(q.get("cloths") or ())) for q in (t or {}).get("squares") or []}
    theirs = {(r["cell"], r["size"], r["count"], r["moving"], r["fighting"], tuple(r[k] for k in CLOTH_COLS)) for r in auth or []}
    return len(mine & theirs), len(theirs), len(mine)


@scenario("heed-throng", explicit=True)
def heed_throng(run, c):
    """The throng drawn (heed for players; features/heed.md): a 200-fighter sides battle
    (`spawn_battle_sides`, admin) beside the player, first with the heed laws off (the set and
    the drawing as before heed: no `seen_throng`, no throng, no keeping-track rows in Settings),
    then both laws on (`set_world_law`, admin): the client subscribes `seen_throng` beside the
    rest, make-before-break, and draws each row as `count` figure cards in its square with the
    poses its shares give, cloth colours derived from the look book in proportion to the 10-word
    `cloth_*` histogram, and cards centred on `(cell corner + centre_x/y + 0.5 m)`, at the play
    camera and zoomed out; Settings' switch hides them; then `heed_players` off: the rows go and
    the set is the first one again. The laws go back to the world's own values after."""
    s = "heed-throng"
    plan = ("ready;wait:2;sync:battle;wait:5;dump:off;shot:off;"
            "click:@menu;wait:0.5;click:@menu:Settings;wait:0.8;dump:settings_off;click:@settings:page:controls;wait:0.6;dump:controls_off;click:@settings:page:play;wait:0.4;click:@win:Settings:close;wait:0.5;"
            "sync:heed;wait:8;sync:rows_on_a;dump:on;sync:rows_on_b;shot:on;"
            "notches:-12;wait:4;sync:rows_far_a;dump:far;sync:rows_far_b;shot:far;notches:12;wait:3;"
            "click:@menu;wait:0.5;click:@menu:Settings;wait:0.8;dump:settings_on;click:@settings:page:controls;wait:0.6;dump:controls_on;click:@settings:page:play;wait:0.4;"
            "click:@settings:throng;wait:1.2;dump:hidden;shot:hidden;"
            "click:@settings:throng;wait:1.2;dump:shown;click:@win:Settings:close;wait:0.5;"
            "sync:off;wait:4;dump:after;sync:rows_after;shot:after;quit")

    def battle(me, ident):
        # Noon, so the player sees the whole battle (the island's night sight is short); the
        # world's epoch is put back after (`sight_fixture`).
        calls = [verify_sql_noon(run), call_admin(run, "spawn_battle_sides", [200, 2], check=True)]
        names = {r["id"]: r["name"] for r in sql(run, "SELECT id, name FROM character WHERE kind = 'person'") if re.fullmatch(r"[AB]\d+", r.get("name") or "")}
        pos = [(b["x"], b["y"]) for b in sql(run, "SELECT id, x, y FROM body") if b["id"] in names]
        cx, cy = sum(p[0] for p in pos) / len(pos), sum(p[1] for p in pos) / len(pos)
        # At the battle's south edge, looking at it (north up on the default camera).
        calls.append(call_admin(run, "place_at", [me, cx, cy + 9.0], check=True))
        return {"fighters": len(pos), "centre": [cx, cy], "calls": calls}

    handlers = {
        "battle": battle,
        "heed": lambda me, ident: [call_admin(run, r, a, check=True) for r, a in heed_on_calls()],
        "rows_on_a": lambda me, ident: throng_rows(run, ident),
        "rows_on_b": lambda me, ident: throng_rows(run, ident),
        "rows_far_a": lambda me, ident: throng_rows(run, ident),
        "rows_far_b": lambda me, ident: throng_rows(run, ident),
        "off": lambda me, ident: call_admin(run, "set_world_law", ["heed_players", "false"], check=True),
        "rows_after": lambda me, ident: throng_rows(run, ident),
    }
    with heed_fixture(run), sight_fixture(run, {}):
        out, code, text, res = staged_drive(run, s, plan, handlers)
    c.check(s, "client ran and joined", code == 0, text[-300:])
    d = {k: dump(out, k) or {} for k in ("off", "settings_off", "controls_off", "on", "far", "settings_on", "controls_on", "hidden", "shown", "after")}
    L = log(out)
    c.check(s, "the battle is spawned beside the player", (res.get("battle") or {}).get("fighters", 0) >= 150, json.dumps(res.get("battle"))[:300])
    sets = perception_sets(L)
    first, laws_on = (sets[0] if sets else None), [x for x in sets if "throng true" in x[1]]
    # Laws off: the set and the drawing as before heed.
    c.check(s, "laws off: no throng and no heed in the dump, and the set has no seen_throng", d["off"].get("throng") is None and d["off"].get("heed") is None and first is not None and "throng" not in first[1], f"first set {first}")
    tags_off, keys_off = d["settings_off"].get("tags") or {}, d["controls_off"].get("tags") or {}
    c.check(s, "laws off: Settings shows no throng switch and no keeping-track keys", "settings:page:play" in tags_off and "settings:throng" not in tags_off and "bind:NorthUp:0" in keys_off and not any(t.startswith("bind:Pin") or t.startswith("bind:ClearPins") for t in keys_off), str(sorted(t for t in list(tags_off) + list(keys_off) if "throng" in t or "Pin" in t)))
    # Laws on: one more query, make-before-break.
    c.check(s, "laws on: the set is subscribed again with seen_throng (one query more), then switched to", bool(laws_on) and first is not None and int(laws_on[0][0]) == int(first[0]) + 1 and re.search(r"perception: on the \w+ set after \d+ ms \([^)]*throng true", L) is not None, f"{first} -> {laws_on[:1]}")
    c.check(s, "laws on: the log names heed for players", "rules: heed for players true" in L and "heed: players heed true" in L)
    for k, rows_k in (("on", "rows_on_a"), ("far", "rows_far_a")):
        t = d[k].get("throng") or {}
        sqs = t.get("squares") or []
        bad = squares_ok(t)
        c.check(s, f"{k}: the throng has rows and every square is drawn as its row says (count cards, poses, colours, centroids, inside)", t.get("rows", 0) > 0 and not bad and t.get("tint") == "book", f"rows {t.get('rows')} cards {t.get('cards')} tint {t.get('tint')}; bad {bad[:2]}")
        distinct_rgbs = {rgb for q in sqs for rgb in (q.get("rgb") or {})}
        tinted_total = sum(q.get("tinted", 0) for q in sqs)
        non_origin_centres = any(q.get("centre") != [0, 0] for q in sqs)
        wide_sqs = [q for q in sqs if _expected_cloth_alloc(q, True)[1] > 3]
        wide_ok = all(len(q.get("rgb") or {}) > 3 for q in wide_sqs)
        c.check(s, f"{k}: cards carry real look-book cloth colours from the full histogram (>3 words in dense cells) and non-trivial centroids",
                tinted_total > 0 and len(distinct_rgbs) >= 2 and non_origin_centres and wide_ok,
                f"tinted {tinted_total}, rgbs {sorted(distinct_rgbs)}, wide {[(q.get('cell'), len(q.get('rgb') or {}), q.get('cloths')) for q in wide_sqs[:3]]}, centres {[q.get('centre') for q in sqs[:4]]}")
        # The authority's rows just before and just after the dump: a row the battle changed
        # in between counts as alike when it matches either.
        both = (res.get(rows_k) or []) + (res.get(rows_k[:-1] + "b") or [])
        same, theirs, mine = rows_match(t, both)
        n = len(res.get(rows_k) or [])
        c.check(s, f"{k}: the client's rows are the authority's (owner SQL just before and after the dump)", n > 0 and same >= 0.8 * mine and abs(mine - n) <= max(3, n // 5), f"{same} of the client's {mine} alike; the authority {n} rows")
        c.check(s, f"{k}: the cards drawn total the rows' counts", t.get("cards") == t.get("count"), f"cards {t.get('cards')} count {t.get('count')}")
    tags_on, keys_on = d["settings_on"].get("tags") or {}, d["controls_on"].get("tags") or {}
    c.check(s, "laws on: Settings shows the throng switch and the keeping-track keys", "settings:throng" in tags_on and "bind:Pin:0" in keys_on and "bind:ClearPins:0" in keys_on, str(sorted(t for t in list(tags_on) + list(keys_on) if "throng" in t or "Pin" in t)))
    th, ts = d["hidden"].get("throng") or {}, d["shown"].get("throng") or {}
    c.check(s, "the switch off: no cards drawn, the rows still received", th.get("drawn") is False and th.get("cards") == 0 and th.get("on") is True, json.dumps({k: th.get(k) for k in ("on", "drawn", "cards", "leaving")}))
    c.check(s, "the switch on again: drawn", ts.get("drawn") is True and ts.get("cards", 0) > 0, json.dumps({k: ts.get(k) for k in ("on", "drawn", "cards")}))
    c.check(s, "heed_players off: the dump has no throng or heed, the authority no rows of mine", d["after"].get("throng") is None and d["after"].get("heed") is None and res.get("rows_after") == [], f"{len(res.get('rows_after') or [])} rows")
    c.check(s, "heed_players off: the set is the first one again", bool(sets) and sets[-1] == first, f"{first} ... {sets[-1] if sets else None}")
    c.check(s, "the heed laws are back to the world's own values", all(own_laws(lambda q: sql(run, q)).get(l, "false") == "false" for l in ("heed_on", "heed_players")))


@scenario("heed-pins", explicit=True)
def heed_pins(run, c):
    """Pins, focus, throng-card click (`pin_at`), refused `pin_at` and a mixed people-and-wolf
    cell (heed for players; features/heed.md): the player at a quiet open spot (`UNHEARD_SPOT`,
    admin `place_at`), five residents held beside them, both heed laws on (admin). The Pin key (T)
    on four of them pins them (the authority's `heed_choice` row holds the four, owner SQL), on a
    fifth warns first, and a second press asks: the authority refuses it in its own words, shown in
    the notes. T on a pinned one unpins it. Focus follows whom the open text box speaks to, and
    goes when it closes. Y clears every pin. Then `heed_ceiling` is lowered to 2 and E placed in
    its own 6 m cell 6.5 m east so E enters `seen_throng`: left-clicking (`tap`) E's throng card
    sends `pin_at` and promotes + pins E; asking for `pin_at` at an empty point (`heed:at:…`) is
    refused with `There is no one in the throng there to pick out.`. Finally, if the world has
    living wolves, three residents and two wolves are placed in that same 6 m cell while two close
    residents stay pinned, verifying per-kind card counts (`people: 3, wolf: 2`) and that only
    people take cloth tints."""
    s = "heed-pins"
    ids = residents(run, 5)
    c.check(s, "five residents to pin", len(ids) == 5, str(ids))
    if len(ids) < 5:
        return
    wolves = sorted(r["id"] for r in sql(run, "SELECT id, alive, kind FROM character WHERE kind = 'wolf'") if r.get("alive"))[:2]
    A, B, C, D, E = ids
    offsets = [(1.6, 0.0), (-1.6, 0.0), (0.0, 1.6), (1.2, 1.4), (-1.2, 1.4)]
    places = [f"{i}:{dx}:{dy}" for i, (dx, dy) in zip(ids, offsets)]
    pin = lambda i: f"point:{i}:1.0;wait:0.3;key:KeyT:tap;wait:0.7;"
    ax, ay = UNHEARD_SPOT
    # Cell (51, 55): origin (306.0, 330.0); E stands at (306.5, 330.5) so its 1-member centroid is exact.
    ex, ey = math.floor(ax / 6.0) * 6.0 + 6.5, math.floor(ay / 6.0) * 6.0 + 0.5
    mix_plan = ""
    if len(wolves) == 2:
        mix_plan = "sync:mix_setup;wait:2.5;dump:mixed;shot:mixed;"
    plan = ("ready;wait:2;sync:spot;wait:3;sync:scene;wait:1;sync:heed;wait:4;dump:p0;"
            + pin(A) + pin(B) + pin(C) + pin(D) + "wait:0.6;dump:p4;sync:row4;"
            + f"point:{E}:1.0;wait:0.3;key:KeyT:tap;wait:0.6;dump:warn;key:KeyT:tap;wait:1.5;dump:five;shot:five;sync:row5;"
            + pin(B) + "wait:0.6;dump:unpin;sync:row_unpin;"
            + f"point:{C}:1.0;wait:0.6;key:Enter:tap;wait:1.5;dump:focus;sync:row_focus;shot:focus;key:Escape:tap;wait:1.5;dump:nofocus;sync:row_nofocus;"
            + "cursor:;key:KeyY:tap;wait:1.2;dump:clear;sync:row_clear;"
            + f"sync:throng_setup;wait:3.8;dump:throng_before;"
            + f"pointat:{ex},{ey}:0.6;wait:0.4;tap;wait:1.5;dump:pin_at;sync:row_pin_at;shot:pin_at;"
            + f"cursor:;heed:at:{ax - 30.0},{ay - 30.0};wait:1.2;dump:pin_at_empty;sync:row_pin_at_empty;"
            + mix_plan
            + "quit")
    row = lambda me, ident: heed_choice(run, me)

    def spot(me, ident):
        return [verify_sql_noon(run), call_admin(run, "place_at", [me, ax, ay], check=True)]

    def throng_setup(me, ident):
        return [
            call_admin(run, "set_world_law", ["heed_ceiling", "2"], check=True),
            call_admin(run, "place_at", [B, ax + 3.5, ay], check=True),
            call_admin(run, "place_at", [C, ax - 3.5, ay], check=True),
            call_admin(run, "place_at", [D, ax, ay + 3.5], check=True),
            call_admin(run, "place_at", [E, ex, ey], check=True),
        ]

    def mix_setup(me, ident):
        idle = json.dumps({"wait": 60})
        # Keep A (at 1.6 m) and E (pinned, moved to 1.6 m) as the 2 individuals (heed_ceiling = 2),
        # and place B, C, D + 2 idle wolves together in cell (51, 55) so they form one mixed cell.
        calls = [
            call_admin(run, "place_at", [E, ax - 1.6, ay], check=True),
            call_admin(run, "place_at", [B, ex + 0.8, ey + 0.5], check=True),
            call_admin(run, "place_at", [C, ex + 1.6, ey + 0.5], check=True),
            call_admin(run, "place_at", [D, ex + 2.4, ey + 0.5], check=True),
        ]
        for idx, wid in enumerate(wolves):
            calls.append(call_admin(run, "set_behavior", [wid, idle], check=True))
            calls.append(call_admin(run, "place_at", [wid, ex + 1.0 + idx * 1.4, ey + 2.2], check=True))
        return calls

    handlers = {
        "spot": spot,
        "heed": lambda me, ident: [call_admin(run, r, a, check=True) for r, a in heed_on_calls()],
        "row4": row, "row5": row, "row_unpin": row, "row_focus": row, "row_nofocus": row, "row_clear": row,
        "throng_setup": throng_setup,
        "row_pin_at": lambda me, ident: {"choice": heed_choice(run, me), "throng": throng_rows(run, ident)},
        "row_pin_at_empty": row,
    }
    if len(wolves) == 2:
        handlers["mix_setup"] = mix_setup
    borrow = ids + wolves
    with resident_fixture(run, borrow), heed_fixture(run), sight_fixture(run, {}):
        out, code, text, res = staged_drive(run, s, plan, handlers, extra=[x for p in places for x in ("--place", p)])
    c.check(s, "client ran and joined", code == 0, text[-300:])
    keys_d = ["p0", "p4", "warn", "five", "unpin", "focus", "nofocus", "clear", "throng_before", "pin_at", "pin_at_empty"]
    if len(wolves) == 2:
        keys_d.append("mixed")
    d = {k: dump(out, k) or {} for k in keys_d}
    h = {k: d[k].get("heed") or {} for k in d}
    c.check(s, "heed for players is on and the five are individuals", h["p0"].get("on") is True and set(ids) <= set(d["p0"].get("perceived") or []), f"perceived {d['p0'].get('perceived')}")
    c.check(s, "four pinned, and the authority holds the four", h["p4"].get("pins") == [A, B, C, D] and (res.get("row4") or {}).get("pins") == [A, B, C, D], f"client {h['p4'].get('pins')}; authority {res.get('row4')}")
    c.check(s, "a fifth is warned about first, not sent", h["warn"].get("pins") == [A, B, C, D] and any("4 already" in n for n in d["warn"].get("notes") or []) and HEED_MAX not in (h["warn"].get("refusals") or []), f"{d['warn'].get('notes')}")
    c.check(s, "asked again, the authority refuses the fifth in its exact words, shown in the notes", HEED_MAX in (h["five"].get("refusals") or []) and HEED_MAX in (d["five"].get("notes") or []), f"refusals {h['five'].get('refusals')}; notes {d['five'].get('notes')}")
    c.check(s, "after the refusal the authority still holds the four, and so does the client", h["five"].get("pins") == [A, B, C, D] and (res.get("row5") or {}).get("pins") == [A, B, C, D], f"{h['five'].get('pins')}; {res.get('row5')}")
    c.check(s, "T on a pinned one unpins them, here and on the authority", h["unpin"].get("pins") == [A, C, D] and (res.get("row_unpin") or {}).get("pins") == [A, C, D], f"{h['unpin'].get('pins')}; {res.get('row_unpin')}")
    t = d["focus"].get("typing") or {}
    c.check(s, "focus follows whom the open box speaks to, here and on the authority", t.get("to") == C and h["focus"].get("focus") == C and (res.get("row_focus") or {}).get("focus") == C, f"to {t.get('to')}; focus {h['focus'].get('focus')}; authority {res.get('row_focus')}")
    c.check(s, "the box closed: no focus, here and on the authority", h["nofocus"].get("focus") is None and (res.get("row_nofocus") or {}).get("focus") is None, f"{h['nofocus'].get('focus')}; {res.get('row_nofocus')}")
    rc = res.get("row_clear")
    c.check(s, "Y clears every pin (the authority's row empty or gone)", h["clear"].get("pins") == [] and (rc is None or (rc.get("pins") == [] and rc.get("focus") is None)), f"{h['clear'].get('pins')}; {rc}")
    # pin_at: E is in seen_throng before the click, promoted to perceived and pinned after clicking its card.
    tb = d["throng_before"].get("throng") or {}
    cell_e = [int(ex // 6), int(ey // 6)]
    sq_e = next((q for q in (tb.get("squares") or []) if q.get("cell") == cell_e), None)
    c.check(s, "pin_at setup: E is in the throng square and not perceived", E not in (d["throng_before"].get("perceived") or []) and sq_e is not None and sq_e.get("count") == 1, f"perceived {d['throng_before'].get('perceived')}; sq {sq_e}")
    row_pin_at_choice = (res.get("row_pin_at") or {}).get("choice") or {}
    row_pin_at_throng = (res.get("row_pin_at") or {}).get("throng") or []
    c.check(s, "clicking E's throng card promotes E to perceived and pins E here and on the authority",
            E in (d["pin_at"].get("perceived") or []) and E in (h["pin_at"].get("pins") or []) and h["pin_at"].get("last_picked") == E and E in (row_pin_at_choice.get("pins") or []),
            f"perceived {d['pin_at'].get('perceived')}; heed {h['pin_at']}; authority {row_pin_at_choice}")
    tp = d["pin_at"].get("throng") or {}
    sq_e_after = next((q for q in (tp.get("squares") or []) if q.get("cell") == cell_e), None)
    cell_e_key = (cell_e[0] << 16) | cell_e[1]
    auth_e_after = [r for r in row_pin_at_throng if r.get("cell") == cell_e_key]
    pick_cell = h["pin_at"].get("last_pick_cell")
    c.check(s, "pin_at removes E from its throng cell in the same update",
            pick_cell == {"cell": cell_e, "before": 1, "after": 0} and sq_e_after is None and not auth_e_after,
            f"last_pick_cell {pick_cell}; sq_after {sq_e_after}; auth_after {auth_e_after}")
    # Refused pin_at at an empty point: exact authority words, existing pin kept.
    c.check(s, "pin_at at an empty point: refused with exact words in notes, existing pin kept",
            HEED_EMPTY in (h["pin_at_empty"].get("refusals") or []) and HEED_EMPTY in (d["pin_at_empty"].get("notes") or []) and E in ((res.get("row_pin_at_empty") or {}).get("pins") or []),
            f"refusals {h['pin_at_empty'].get('refusals')}; notes {d['pin_at_empty'].get('notes')}; authority {res.get('row_pin_at_empty')}")
    if len(wolves) == 2:
        tm = d["mixed"].get("throng") or {}
        sq_m = next((q for q in (tm.get("squares") or []) if q.get("cell") == cell_e), None)
        ck = (sq_m or {}).get("card_kinds") or {}
        c.check(s, "mixed people-and-wolf cell draws 3 people and 2 wolves by per-kind counts, only people tinted",
                sq_m is not None and sq_m.get("by_kind") == [3, 2, 0, 0] and ck.get("person") == 3 and ck.get("wolf") == 2 and sq_m.get("animals") == 2 and 0 < sq_m.get("tinted", 0) <= 3 and not squares_ok(tm),
                f"sq {sq_m}")
    L = log(out)
    stamps = [x for x in re.findall(r"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d+)Z[^\n]*heed: sent", L)]
    import datetime
    ts = [datetime.datetime.fromisoformat(x).timestamp() for x in stamps]
    gaps = [round(b - a, 3) for a, b in zip(ts, ts[1:])]
    c.check(s, "calls at least 250 ms apart, none refused as too many inputs", len(ts) >= 8 and all(g >= 0.25 for g in gaps) and "refused (paced)" not in L, f"{len(ts)} calls; gaps {gaps}")
    notes_clear(c, s, out)


@scenario("heed-refusal", explicit=True)
def heed_refusal(run, c):
    """The authority's words for someone I do not perceive (heed for players; features/heed.md):
    both heed laws on (admin), a resident put 80 m off, then the live script asks to pin them as
    they are (`heed:ID`, past the client's own check), then an id no one has: both refused with
    the same words, shown in the notes; the authority's row holds neither."""
    s = "heed-refusal"
    far = residents(run, 1)[0]
    nobody = 4_000_000_000
    plan = (f"ready;wait:2;sync:heed;wait:3;dump:r0;heed:{far};wait:1.2;dump:r1;shot:refusal;heed:{nobody};wait:1.2;dump:r2;sync:row;quit")
    handlers = {
        "heed": lambda me, ident: [call_admin(run, r, a, check=True) for r, a in heed_on_calls()] + [call_admin(run, "place_at", [far] + [v + 80.0 for v in (sql(run, f"SELECT x, y FROM body WHERE id = {me}") or [{"x": 0, "y": 0}])[0].values()], check=True)],
        "row": lambda me, ident: heed_choice(run, me),
    }
    with resident_fixture(run, [far]), heed_fixture(run):
        out, code, text, res = staged_drive(run, s, plan, handlers)
    c.check(s, "client ran and joined", code == 0, text[-300:])
    d = {k: dump(out, k) or {} for k in ("r0", "r1", "r2")}
    c.check(s, "the far resident is not perceived", far not in (d["r0"].get("perceived") or []), str(d["r0"].get("perceived")))
    r1, r2 = (d["r1"].get("heed") or {}).get("refusals") or [], (d["r2"].get("heed") or {}).get("refusals") or []
    c.check(s, "pinning someone not perceived: the authority's exact words, in the notes", HEED_UNSEEN in r1 and HEED_UNSEEN in (d["r1"].get("notes") or []), f"{r1}; {d['r1'].get('notes')}")
    c.check(s, "an id no one has: the same words", r2.count(HEED_UNSEEN) >= 2, str(r2))
    row = res.get("row")
    c.check(s, "the authority's row names neither", row is None or (far not in row.get("pins", []) and nobody not in row.get("pins", [])), str(row))


@scenario("windup", explicit=True)
def windup(run, c):
    """Combat clip timing (B, default live) and hostile windup midpoint glint (A, default off;
    features/bar.md):
    1. Defaults (`combat_timing=live`, `windup_glint=false`): hostile strikes start their clip
       during the windup before release; zero glints fire.
    2. Old timing (`settings:combat_timing:old`): hostile strikes wait for the delayed display
       clock `now_ms` (matching main); zero glints fire.
    3. Live + glint on (`settings:combat_timing:live`, `settings:windup_glint`): one glint fires
       per hostile windup at `f >= 0.5` (`extra.glints` and `client.log`), never for my own
       character, and the clip starts before release."""
    s = "windup"
    attacker = residents(run, 1)[0]
    spot = (360.5, 232.5)
    att_at = (spot[0] - 1.2, spot[1] - 1.2)
    dmg0 = own_laws(lambda q: sql(run, q)).get("dmg_strike", "5")
    out_dir = os.path.join(ROOT, ".local/living/verify", run, "ui", f"{s}-{THEME}" if THEME else s)
    feet_path = os.path.join(out_dir, "feet.jsonl")
    # Remove any prior scratch settings.json so defaults are verified cleanly on re-runs.
    prior_settings = os.path.join(out_dir, "settings.json")
    if os.path.exists(prior_settings):
        os.remove(prior_settings)
    open_settings = "click:@menu;wait:0.4;click:@menu:Settings;wait:0.5;"
    plan = (
        "ready;sync:setup;wait:1.0;dump:def0;"
        "sync:fight_live;wait:4.2;sync:hold1;dump:def1;"
        + open_settings + "shot:01_settings;click:@settings:combat_timing:old;wait:0.4;dump:old0;key:Escape:tap;wait:0.6;"
        "sync:fight_old;wait:4.2;sync:hold2;dump:old1;"
        + open_settings + "click:@settings:combat_timing:live;wait:0.3;click:@settings:windup_glint;wait:0.4;dump:glint0;shot:02_settings_glint;key:Escape:tap;wait:0.6;"
        "weapon:draw;wait:0.3;sync:fight_glint;wait:1.0;skill:strike:nearest;wait:3.6;sync:hold3;dump:glint1;shot:03_glint_done;quit"
    )
    idle_g = json.dumps({"wait": 600})
    def strike_graph(me):
        return json.dumps({"first": [{"do": {"skill": "strike", "target": {"id": me}}}, {"wait": 1}]})
    handlers = {
        "setup": lambda me, ident: [
            call_admin(run, "set_world_law", ["dmg_strike", "1"], check=True),
            verify_sql_noon(run),
            call_admin(run, "place_at", [me, spot[0], spot[1]], check=True),
            call_admin(run, "place_at", [attacker, att_at[0], att_at[1]], check=True),
            call_admin(run, "set_behavior", [attacker, idle_g], check=True),
        ],
        "fight_live": lambda me, ident: [call_admin(run, "set_behavior", [attacker, strike_graph(me)], check=True)],
        "fight_old": lambda me, ident: [call_admin(run, "set_behavior", [attacker, strike_graph(me)], check=True)],
        "fight_glint": lambda me, ident: [call_admin(run, "set_behavior", [attacker, strike_graph(me)], check=True)],
        "hold1": lambda me, ident: [call_admin(run, "set_behavior", [attacker, idle_g], check=True)],
        "hold2": lambda me, ident: [call_admin(run, "set_behavior", [attacker, idle_g], check=True)],
        "hold3": lambda me, ident: [call_admin(run, "set_behavior", [attacker, idle_g], check=True)],
    }
    env = {"LIVING_GAME_FEET": feet_path, "LIVING_GAME_FEET_ID": str(attacker)}
    try:
        with resident_fixture(run, [attacker]):
            out, code, text, _ = staged_drive(run, s, plan, handlers, env=env)
    finally:
        call_admin(run, "set_world_law", ["dmg_strike", dmg0])
    c.check(s, "client ran and joined", code == 0, text[-300:])
    d = {k: dump(out, k) or {} for k in ("def0", "def1", "old0", "old1", "glint0", "glint1")}
    ex = lambda k: d[k].get("extra") or {}
    c.check(s, "defaults: combat_timing is live and windup_glint is off",
            ex("def0").get("combat_timing") == "live" and ex("def0").get("windup_glint") is False,
            f"{ex('def0').get('combat_timing')}, {ex('def0').get('windup_glint')}")
    c.check(s, "defaults: no glint fires while windup_glint is off",
            (ex("def1").get("glints") or []) == [],
            str(ex("def1").get("glints")))
    c.check(s, "Settings switches combat_timing to old",
            ex("old0").get("combat_timing") == "old" and ex("old0").get("windup_glint") is False,
            f"{ex('old0').get('combat_timing')}, {ex('old0').get('windup_glint')}")
    c.check(s, "old timing: no glint fires while windup_glint is off",
            (ex("old1").get("glints") or []) == [],
            str(ex("old1").get("glints")))
    c.check(s, "Settings switches back to live and enables windup_glint",
            ex("glint0").get("combat_timing") == "live" and ex("glint0").get("windup_glint") is True,
            f"{ex('glint0').get('combat_timing')}, {ex('glint0').get('windup_glint')}")
    glints = ex("glint1").get("glints") or []
    sc = json.load(open(os.path.join(out, "scene.json"))) if os.path.exists(os.path.join(out, "scene.json")) else {}
    me = sc.get("me")
    keys = [(g.get("actor"), g.get("act_ms")) for g in glints]
    fs = [g.get("f") for g in glints]
    c.check(s, "windup_glint on: fires once per hostile windup at f >= 0.5, never for my own character",
            len(glints) >= 2
            and len(keys) == len(set(keys))
            and all(g.get("actor") == attacker for g in glints)
            and all(g.get("actor") != me for g in glints)
            and all(f is not None and 0.5 <= f < 1.0 for f in fs),
            f"me={me} attacker={attacker} glints={glints}")
    # Check clip timing from feet.jsonl: group strikes by act_ms, split into live vs old phases
    # using the client log's settings switch timestamps.
    L = log(out)
    glint_logs = re.findall(rf"combat: windup glint #{attacker} act_ms=(\d+) release_ms=(\d+) f=([0-9.]+)", L)
    c.check(s, "windup glint lines logged in client.log match dump count",
            len(glint_logs) == len(glints) and len(glint_logs) >= 2,
            f"log={len(glint_logs)} dump={len(glints)}")
    rows = []
    if os.path.exists(feet_path):
        with open(feet_path) as fh:
            for line in fh:
                if line.strip():
                    r = json.loads(line)
                    if r.get("id") == attacker:
                        rows.append(r)
    # Identify each distinct strike by action start_ms and find when the sword_* clip first dominates.
    # Use the dumps' live-script log times (`t X.XXX s`) to partition live / old / glint phases.
    t_def0 = re.search(r"live script: dump:def0 .* t ([0-9.]+) s", L)
    t_def1 = re.search(r"live script: dump:def1 .* t ([0-9.]+) s", L)
    t_old0 = re.search(r"live script: dump:old0 .* t ([0-9.]+) s", L)
    t_old1 = re.search(r"live script: dump:old1 .* t ([0-9.]+) s", L)
    def phase_onsets(t0, t1):
        sub = [r for r in rows if t0 <= r.get("t", 0.0) <= t1]
        by_act = {}
        for r in sub:
            act = r.get("action")
            if isinstance(act, list) and len(act) == 2 and str(act[0]).startswith("sword"):
                by_act.setdefault(int(act[1]), []).append(r)
        out_ms = []
        for act_ms, frames in sorted(by_act.items()):
            want_clip = frames[0]["action"][0]
            # Find first frame for this blow where its clip dominates (filter out previous blow's tail).
            dom = next((r for r in frames if r.get("mine_ms") is not None and r.get("clip") == want_clip and r["mine_ms"] >= act_ms - 10), None)
            if dom is not None:
                lead = (dom["mine_ms"] - dom["now_ms"]) if dom.get("now_ms") is not None else 0.0
                now_delta = round(dom["now_ms"] - act_ms, 1) if dom.get("now_ms") is not None else None
                out_ms.append((act_ms, round(dom["mine_ms"] - act_ms, 1), round(lead, 1), now_delta, dom.get("clip")))
        return out_ms
    live_onsets = phase_onsets(float(t_def0.group(1)), float(t_def1.group(1))) if t_def0 and t_def1 else []
    old_onsets = phase_onsets(float(t_old0.group(1)), float(t_old1.group(1))) if t_old0 and t_old1 else []
    c.check(s, "live timing: combat clip dominates during the 350 ms windup (before release)",
            len(live_onsets) >= 2 and all(d < 350.0 for _, d, _, _, _ in live_onsets),
            f"live_onsets={live_onsets}")
    c.check(s, "old timing: clip onset waits for delayed display clock now_ms >= act_ms",
            len(old_onsets) >= 2 and all(nd is not None and nd >= -5.0 for _, _, _, nd, _ in old_onsets),
            f"live={live_onsets} old={old_onsets}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run")
    ap.add_argument("--list", action="store_true", help="print the registered scenarios, one per line (* needs a Cullet world), and exit")
    ap.add_argument("scenarios", nargs="*")
    a = ap.parse_args()
    if a.list:
        print("\n".join(n + (" *" if n in CULLET else "") + (" (launches its own world)" if n in FRESH else "") for n in SCENARIOS))
        return
    if not a.run:
        ap.error("--run is required")
    # gate-*: the scene gate's render group (living/tools/scene_gate.py), on its own verify-gate-* worlds.
    if not f"verify-{a.run}".startswith(("verify-ui-", "verify-gate-")):
        sys.exit("verify-ui runs use run names ui-* (worlds verify-ui-*), or the scene gate's gate-*")
    c = Checks()
    owner = None
    # Special seed fixtures require a scenario name on the command line.
    for name in a.scenarios or [k for k in SCENARIOS if k not in CULLET and k not in EXPLICIT]:
        if name not in SCENARIOS:
            sys.exit(f"unknown scenario {name}; known: {', '.join(SCENARIOS)}")
        owner = owner or verify.admin_token()
        if name not in FRESH:
            verify.require_running(verify.load(a.run), owner)
        SCENARIOS[name](a.run, c)
    p = os.path.join(ROOT, ".local/living/verify", a.run, "ui", f"checks{BEARING_SUFFIX}.json")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    json.dump(c.rows, open(p, "w"), indent=1)
    failed = [r for r in c.rows if not r["ok"]]
    print(f"{len(c.rows) - len(failed)} passed, {len(failed)} failed; {p}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
