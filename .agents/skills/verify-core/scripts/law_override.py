#!/usr/bin/env python3
"""The world's own law values on a running world (`law_override`, docs/LAW_OVERRIDE.md).

    law_override.py time   --run R [--repeat 3]   (any module: main's too, for the before)
    law_override.py checks --run R                (this branch's module)

`time` changes laws with `set_world_law` as the admin and reads each call's reducer time from the
module's own timing spans in the database log (`set_world_law`, `set_world_law.value_only`,
`install.compile`, `install.validate`), with the HTTP round trip and the first tick after the
commit (`set_profile` on for the run's ticks). The value-only laws of the seed (the delivery laws,
`gaze_on`, and on a world with cover geometry the cover laws) each go to their other value and
back `--repeat` times; `fire_warmth`, an ordinary law, is the full-install reference. On a module
without the `set_world_law` span (main before law-override) the install spans and the round trip
are the measure. Writes `RUN/law-time.json`.

`checks` proves the value-only path's contract on the branch's module:
- `law_override` is public and read-only: anonymous SQL reads every row; `law_revision` is private;
  `set_world_law` from a player is refused ("admin only") with nothing written;
- cover geometry after creation (docs/COVER_SIGHT.md, "Cover geometry"): on a land made with
  its cover law off (the island) there are no `cover_ground` bands; `cover_sight_on` true is
  accepted, `cover_law` stays false while `cover_step` derives the bands in steps, then every band
  is kept, the derivation row says done, a further law revision is written and `cover_law` turns
  true; `cover_derivation` is private. Cover is switched off again, and the world has its geometry
  for the value-only checks below;
- a value-only edit (`cue_transport_on`, `near_tier_on`, `gaze_on`, cover laws on a world with
  cover geometry) writes its row and the next law revision, keeps the script revision and the
  script row, records `law_change` (the script revision in force) and a chronicle line
  "value only"; the cover laws' `cover_law` row follows at once;
- an ordinary law (`fire_warmth`) and a source edit (`install_script`) still install in full: a
  new script revision, the values written at the script's end, `law_override` kept;
- refusals leave nothing written (`law_override`, `law_revision`, `law_change`, the script): a
  value of another kind, a name that is not a law, and, on a world without gaze, `gaze_on` true
  under an installed overlay whose `gaze_ceiling` is out of bounds (refused by the value-only
  path's derived check after its rows were written: the transaction rolls back); the tick keeps
  running and the next edit takes the same law revision;
- a client's first subscription result holds `law_override` with the value in force, before and
  after an edit, each on a fresh connection (the verify-client probe, `drive.py --query`).
Writes `RUN/law-checks.json`. Admin calls set the scene; the seed's script is installed again at
the end. Python standard library only.
"""

import argparse
import datetime as dt
import importlib.util
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
HARNESS = ROOT / ".agents/skills/verify/scripts/verify.py"
SPEC = importlib.util.spec_from_file_location("verify_harness", HARNESS)
V = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(V)
ISPEC = importlib.util.spec_from_file_location("install_script", ROOT / "living/tools/install_script.py")
INSTALL = importlib.util.module_from_spec(ISPEC)
ISPEC.loader.exec_module(INSTALL)
DRIVE = ROOT / ".agents/skills/verify-client/scripts/drive.py"
sys.path.insert(0, str(ROOT / "living/tools"))
from law_values import own_laws  # noqa: E402  (the world's own law values)

DELIVERY = ["cue_transport_on", "near_tier_on"]
COVER = [("cover_brush_min_fill", "0.44"), ("cover_sight_on", None)]
SPAN = re.compile(r'^(\S+)\s+\w+: (\w+): Timing span "([^"]+)": ([\d.]+)(ns|µs|us|ms|s)$')
UNIT = {"ns": 1e-6, "µs": 1e-3, "us": 1e-3, "ms": 1.0, "s": 1000.0}


class Run:
    def __init__(self, run):
        self.st = V.load(run)
        self.db = self.st["db"]
        self.token = V.admin_token()
        self.dir = V.run_dir(run)
        self.results = []

    def sql(self, q, token="admin"):
        tok = self.token if token == "admin" else token
        code, body = V.http(f"/v1/database/{self.db}/sql", q, tok, raw=True)
        if code != 200:
            return None, body
        j = json.loads(body)[-1]
        names = [e["name"]["some"] for e in j["schema"]["elements"]]
        return [dict(zip(names, r)) for r in j["rows"]], None

    def rows(self, q, token="admin"):
        r, e = self.sql(q, token)
        if r is None:
            raise RuntimeError(f"{q}: {e[:300]}")
        return r

    def call(self, reducer, args, token="admin", timeout=180):
        V.refresh_lease(self.st)
        t0 = time.time()
        code, body = V.http(f"/v1/database/{self.db}/call/{reducer}", args, self.token if token == "admin" else token, timeout=timeout)
        ms = (time.time() - t0) * 1000
        V.log(self.st, f"call {reducer}{json.dumps(args)[:200]} -> {code} {body.strip()[:200]} ({ms:.1f} ms)")
        return code, body, t0, ms

    def check(self, name, ok, detail=""):
        self.results.append({"check": name, "ok": bool(ok), "detail": detail})
        print(f"{'PASS' if ok else 'FAIL'} {name} {detail if not ok else ''}".rstrip(), flush=True)

    def logs(self, n=4000):
        return V.stdb("logs", "-s", "local", self.db, "-n", str(n)).stdout

    def spans_after(self, t0, names, text=None):
        """The timing spans logged at or after `t0` (epoch s): {span: [ms...]} and the first tick's."""
        text = text if text is not None else self.logs()
        out = {}
        first_tick = None
        for line in text.splitlines():
            m = SPAN.match(line.strip())
            if not m:
                continue
            when = dt.datetime.fromisoformat(m[1].replace("Z", "+00:00")).timestamp()
            if when < t0 - 0.05:
                continue
            ms = float(m[4]) * UNIT[m[5]]
            if m[3] in names:
                out.setdefault(m[3], []).append(round(ms, 3))
            if m[2] == "tick" and m[3] == "tick" and first_tick is None and out:
                first_tick = round(ms, 3)
        return out, first_tick

    def tick(self):
        return self.rows("SELECT tick FROM clock WHERE id = 0")[0]["tick"]

    def ticking(self):
        a = self.tick()
        time.sleep(1.0)
        return self.tick() > a

    def law(self, name):
        r = self.rows(f"SELECT * FROM law_override WHERE name = '{name}'")
        return r[0] if r else None

    def law_rev(self):
        r = self.rows("SELECT revision FROM law_revision WHERE id = 0")
        return r[0]["revision"] if r else None

    def script_rev(self):
        return self.rows("SELECT revision FROM script WHERE name = 'skills'")[0]["revision"]

    def changes(self):
        return self.rows("SELECT * FROM law_change")

    def value_of(self, name):
        """The law's value in force: its `law_override` row (`world_law` on a module from before
        it), else the last value the script row's text gives it (`laws()`, an overlay's, the
        values written at its end)."""
        own = own_laws(self.rows)
        if name in own:
            return own[name]
        src = self.rows("SELECT source FROM script WHERE name = 'skills'")[0]["source"]
        m = re.findall(rf"\b{name}\s*[:=]\s*(true|false|[-\d.]+)", src)
        return m[-1] if m else None

    def save(self, name, data):
        (self.dir / name).write_text(json.dumps(data, indent=2))


def other(v):
    if v in ("true", "false"):
        return "false" if v == "true" else "true"
    return str(round(float(v) + 0.5, 3))


def has_cover(r):
    return bool(r.rows("SELECT id FROM cover_ground WHERE id = 0"))


def timing(r, repeat):
    names = {"set_world_law", "set_world_law.value_only", "install.compile", "install.validate"}
    r.call("set_profile", [True])
    laws = list(DELIVERY) + ["gaze_on"]
    if has_cover(r):
        laws += ["cover_brush_min_fill", "cover_sight_on"]
    samples = []
    try:
        for name in laws + ["fire_warmth"]:
            start = r.value_of(name)
            n = repeat if name != "fire_warmth" else 2
            for i in range(n):
                for value in ([other(start), start] if name != "cover_brush_min_fill" else ["0.44", start]):
                    if not V.http(f"/v1/ping")[0]:
                        pass
                    code, body, t0, ms = r.call("set_world_law", [name, value])
                    time.sleep(0.4)
                    spans, tick = r.spans_after(t0, names)
                    samples.append({"law": name, "value": value, "status": code, "body": body[:200], "round_trip_ms": round(ms, 2), "spans_ms": spans, "first_tick_ms": tick})
                    print(f"{name}={value}: {code} round trip {ms:.1f} ms; spans {spans}; first tick {tick} ms", flush=True)
    finally:
        r.call("set_profile", [False])
    summary = {}
    for s in samples:
        k = s["law"]
        reducer = (s["spans_ms"].get("set_world_law") or [None])[-1]
        summary.setdefault(k, {"reducer_ms": [], "round_trip_ms": [], "validate_ms": [], "first_tick_ms": []})
        summary[k]["reducer_ms"].append(reducer)
        summary[k]["round_trip_ms"].append(s["round_trip_ms"])
        summary[k]["validate_ms"].append((s["spans_ms"].get("install.validate") or [None])[-1])
        summary[k]["first_tick_ms"].append(s["first_tick_ms"])
    r.save("law-time.json", {"db": r.db, "samples": samples, "summary": summary})
    for k, v in summary.items():
        print(f"{k}: reducer {v['reducer_ms']} round trip {v['round_trip_ms']} validate {v['validate_ms']} first tick {v['first_tick_ms']}")


def rebuilds(r, name, value, t0):
    """The map work after a value edit, from the module's spans: the whole map never reloads;
    the cover mask compiles once when a cover law changed while cover is on, else never (a
    delivery or gaze edit, or cover turned off, leaves it as it is)."""
    time.sleep(0.8)
    spans, _ = r.spans_after(t0, {"map.cover", "map.rebuild"})
    on = r.rows("SELECT cover_sight_on FROM cover_law WHERE id = 0")[0]["cover_sight_on"]
    want = 1 if name.startswith("cover_") and on else 0
    got = len(spans.get("map.cover", []))
    r.check(f"{name}={value}: the cover mask compiled {want} time(s), the whole map never", got == want and not spans.get("map.rebuild"), f"{spans}")


def derive_cover(r, timeout_s=300):
    """A land without cover geometry derives it when cover goes on, in force once complete."""
    land = r.rows("SELECT size FROM land")
    if has_cover(r) or not land:
        print("cover geometry: the world has it (or is not a land); the derivation scene is skipped", flush=True)
        return
    bands = (land[0]["size"] ** 2 + 16383) // 16384
    lrev = r.law_rev()
    code, body, _, _ = r.call("set_world_law", ["cover_sight_on", "true"])
    r.check("cover_sight_on true on a land without cover geometry is accepted (derived after)", code == 200, body[:200])
    law = r.rows("SELECT cover_sight_on FROM cover_law WHERE id = 0")[0]["cover_sight_on"]
    r.check("…cover is not in force while the geometry is derived (cover_law false)", law is False, f"{law}")
    rows, _ = r.sql("SELECT * FROM cover_derivation", token=None)
    r.check("cover_derivation is private: anonymous SQL is refused", rows is None, f"{rows}")
    t0, d = time.time(), {}
    while time.time() - t0 < timeout_s:
        got = r.rows("SELECT * FROM cover_derivation")
        d = got[0] if got else {}
        if d.get("done") or str(d.get("label", "")).startswith("stopped"):
            break
        time.sleep(1)
    n = r.rows("SELECT COUNT(*) AS n FROM cover_ground")[0]["n"]
    r.check(f"…derived in steps: {bands} bands kept, the derivation done", d.get("done") is True and n == bands, f"{n} bands; {d}")
    law = r.rows("SELECT cover_sight_on FROM cover_law WHERE id = 0")[0]["cover_sight_on"]
    r.check("…then in force: cover_law true, and a law revision after the switch's", law is True and r.law_rev() >= lrev + 2, f"{law} {r.law_rev()} {lrev}")
    r.save("cover-derivation.json", {"seconds": round(time.time() - t0, 1), "derivation": d, "bands": n})
    code, body, _, _ = r.call("set_world_law", ["cover_sight_on", "false"])
    r.check("cover_sight_on back to false", code == 200, body[:200])


def checks(r, seed):
    anon = None
    code, body = V.http("/v1/identity", {})
    player = json.loads(body)["token"] if code == 200 else None
    r.check("the tick advances", r.ticking())
    # Public and read-only.
    rows, err = r.sql("SELECT * FROM law_override", token=None)
    owner = r.rows("SELECT * FROM law_override")
    r.check("law_override is public: anonymous SQL reads every row", rows is not None and len(rows) == len(owner), f"{err} {len(owner)} rows")
    rows, err = r.sql("SELECT * FROM law_revision", token=None)
    r.check("law_revision is private: anonymous SQL is refused", rows is None, f"{rows}")
    lrev0, srev0, nchanges0 = r.law_rev(), r.script_rev(), len(r.changes())
    r.check("law_revision has its row (world_law copied once)", lrev0 is not None, f"{lrev0}")
    code, body, _, _ = r.call("set_world_law", ["cue_transport_on", "false"], token=player)
    r.check("set_world_law from a player is refused (admin only)", code != 200 and "admin only" in body, body[:200])
    r.check("…with nothing written", (r.law_rev(), r.script_rev(), len(r.changes())) == (lrev0, srev0, nchanges0))
    derive_cover(r)
    # Value-only edits.
    value_only = list(DELIVERY) + ["gaze_on"] + (["cover_brush_min_fill", "cover_sight_on"] if has_cover(r) else [])
    for name in value_only:
        start = r.value_of(name)
        new = "0.44" if name == "cover_brush_min_fill" else other(start)
        lrev, srev, src = r.law_rev(), r.script_rev(), r.rows("SELECT source FROM script WHERE name = 'skills'")[0]["source"]
        code, body, t0, ms = r.call("set_world_law", [name, new])
        row = r.law(name)
        last = r.changes()[-1]
        chron = r.rows("SELECT text FROM chronicle WHERE kind = 'law'")
        ok = code == 200 and row and row["value"] == new and row["revision"] == lrev + 1 and r.law_rev() == lrev + 1
        r.check(f"{name} {start}->{new}: its row at the next law revision", ok, f"{code} {body[:200]} {row} {r.law_rev()}")
        r.check(f"{name}: the script revision and row are kept", r.script_rev() == srev and r.rows("SELECT source FROM script WHERE name = 'skills'")[0]["source"] == src)
        r.check(f"{name}: law_change and the chronicle say value only", last["name"] == name and last["new"] == new and last["revision"] == srev and any(name in c["text"] and "value only" in c["text"] for c in chron), f"{last}")
        if name.startswith("cover_"):
            cl = r.rows("SELECT * FROM cover_law WHERE id = 0")[0]
            got = cl[name]
            want = (new == "true") if new in ("true", "false") else float(new)
            r.check(f"{name}: cover_law follows at once", got == want if isinstance(want, bool) else abs(got - want) < 1e-4, f"{cl}")
        rebuilds(r, name, new, t0)
        # Back to where it was.
        code, body, t0, _ = r.call("set_world_law", [name, start])
        r.check(f"{name}: back to {start}", code == 200 and r.law(name)["value"] == start, body[:200])
        rebuilds(r, name, start, t0)
    # An ordinary law: a full install.
    start = r.value_of("fire_warmth")
    srev = r.script_rev()
    code, body, _, ms = r.call("set_world_law", ["fire_warmth", other(start)])
    src = r.rows("SELECT source FROM script WHERE name = 'skills'")[0]["source"]
    r.check("fire_warmth (ordinary): installs, a new script revision with the value written in", code == 200 and r.script_rev() == srev + 1 and f"fire_warmth: {float(other(start)):.1f}" in src.split(INSTALL.WORLD_LAW_MARK)[-1], f"{code} {ms:.0f} ms")
    r.check("fire_warmth: the chronicle says installed", any("fire_warmth" in c["text"] and "installed" in c["text"] for c in r.rows("SELECT text FROM chronicle WHERE kind = 'law'")))
    r.call("set_world_law", ["fire_warmth", start])
    # A source edit: a full install; law_override kept, its values written at the end.
    r.call("set_world_law", ["cue_transport_on", "false"])
    over = r.rows("SELECT * FROM law_override")
    srev, lrev = r.script_rev(), r.law_rev()
    source, _ = INSTALL.seed_script(seed)
    code, body = INSTALL.install(r.db, source, r.token)
    src = r.rows("SELECT source FROM script WHERE name = 'skills'")[0]["source"]
    r.check("a source edit (install_script) installs in full: a new script revision", code == 200 and r.script_rev() == srev + 1, body[:200])
    r.check("…law_override and the law revision kept; the values written at the script's end", r.rows("SELECT * FROM law_override") == over and r.law_rev() == lrev and "cue_transport_on: false" in src.split(INSTALL.WORLD_LAW_MARK)[-1])
    r.call("set_world_law", ["cue_transport_on", "true"])
    # Refusals leave nothing written.
    before = (r.rows("SELECT * FROM law_override"), r.law_rev(), len(r.changes()), r.script_rev())
    for args, why in [(["gaze_on", "3"], "takes true or false"), (["no_such_law", "1"], "is not a law"), (["cover_eye_height_m", "true"], "takes a number")]:
        code, body, _, _ = r.call("set_world_law", args)
        r.check(f"set_world_law {args} is refused ({why})", code != 200 and why in body, body[:200])
    r.check("…with nothing written", (r.rows("SELECT * FROM law_override"), r.law_rev(), len(r.changes()), r.script_rev()) == before)
    gaze = r.value_of("gaze_on")
    if gaze == "false":
        # A derived check refuses the value after the rows were written: everything rolls back.
        source, _ = INSTALL.seed_script(seed)
        bad = INSTALL.compose_laws(source, "fn gaze_ceiling(band) { 999.0 }\n")
        code, body = INSTALL.install(r.db, bad, r.token)
        r.check("an overlay with a gaze ceiling out of bounds installs while gaze is off", code == 200, body[:200])
        before = (r.rows("SELECT * FROM law_override"), r.law_rev(), len(r.changes()), r.script_rev(), r.rows("SELECT COUNT(*) AS n FROM chronicle WHERE kind = 'law'"))
        code, body, _, _ = r.call("set_world_law", ["gaze_on", "true"])
        r.check("gaze_on true under it is refused by the gaze ceiling's check", code != 200 and "gaze_ceiling" in body, body[:300])
        after = (r.rows("SELECT * FROM law_override"), r.law_rev(), len(r.changes()), r.script_rev(), r.rows("SELECT COUNT(*) AS n FROM chronicle WHERE kind = 'law'"))
        r.check("…rolled back: no override, law revision, law_change, chronicle or script written", after == before, f"{before[1:4]} {after[1:4]}")
        r.check("…and the world ticks on", r.ticking())
        lrev = r.law_rev()
        code, body, _, _ = r.call("set_world_law", ["near_tier_on", "false"])
        r.check("…the next edit takes the same law revision the refused one did", code == 200 and r.law_rev() == lrev + 1 and r.law("near_tier_on")["revision"] == lrev + 1)
        r.call("set_world_law", ["near_tier_on", "true"])
        code, body = INSTALL.install(r.db, source, r.token)
        r.check("the seed's script installed again", code == 200, body[:200])
    # A client's first result holds law_override, on fresh connections before and after an edit.
    def first(label):
        out = subprocess.run([sys.executable, str(DRIVE), "--run", r.st["run"], "--query", "SELECT * FROM law_override", "--seconds", "1", "--save", label], capture_output=True, text=True, timeout=120)
        path = r.dir / f"{label}.jsonl"
        lines = [json.loads(l) for l in path.read_text().splitlines()] if path.exists() else []
        init = next((l for l in lines if l.get("event") == "initial"), None)
        return init, out
    if not r.st["run"].startswith("client-"):
        # drive.py drives `client-*` runs only (verify-client's naming).
        print("SKIP a client's first result: drive.py needs a client-* run name (launch one as client-law-…)", flush=True)
        r.results.append({"check": "a client's first result (skipped: not a client-* run)", "ok": True, "detail": "skipped"})
        r.save("law-checks.json", {"db": r.db, "results": r.results})
        bad = [c for c in r.results if not c["ok"]]
        print(f"{len(r.results) - len(bad)}/{len(r.results)} passed (first-result checks skipped)")
        return 1 if bad else 0
    init, out = first("law-first-before")
    want = {o["name"]: o["value"] for o in r.rows("SELECT * FROM law_override")}
    got = {o["name"]: o["value"] for o in (init or {}).get("tables", {}).get("law_override", [])}
    r.check("an anonymous client's first result holds every law_override row", init is not None and got == want, f"{out.stderr[-300:]} {got} {want}")
    start = r.value_of("near_tier_on")
    r.call("set_world_law", ["near_tier_on", other(start)])
    init, out = first("law-first-after")
    got = {o["name"]: o["value"] for o in (init or {}).get("tables", {}).get("law_override", [])}
    r.check("a reconnecting client's first result holds the new value", got.get("near_tier_on") == other(start), f"{got.get('near_tier_on')}")
    r.call("set_world_law", ["near_tier_on", start])
    r.check("the tick advances at the end", r.ticking())
    r.save("law-checks.json", {"db": r.db, "results": r.results})
    bad = [c for c in r.results if not c["ok"]]
    print(f"{len(r.results) - len(bad)}/{len(r.results)} passed")
    return 1 if bad else 0


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("part", choices=["time", "checks"])
    p.add_argument("--run", required=True)
    p.add_argument("--repeat", type=int, default=3)
    a = p.parse_args()
    r = Run(a.run)
    seed = r.st.get("seed") or "world"
    if not r.ticking():
        sys.exit("the world does not tick")
    if a.part == "time":
        timing(r, a.repeat)
        return 0
    return checks(r, seed)


if __name__ == "__main__":
    sys.exit(main())
