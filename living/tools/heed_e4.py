#!/usr/bin/env python3
"""E4's measures (docs/ATTENTION_E4.md): does heed capacity matter in a fight? Read-only.

  living/tools/heed_e4.py collect --batch B [--container C]   each instance's heed log lines
  living/tools/heed_e4.py report DIR... [--control ARM] [--json OUT]
  living/tools/heed_e4.py selftest

`collect` copies, for every instance of a trial batch (`.local/living/trials/<B>/*`, run with
`--keep-db` so the replicas are still there), the authority's `heed …` lines from its replica's
module log into the instance's `heed.log` (the authority logs them for characters with a mind,
authority/src/heed.rs): `heed windup`, `heed blow`, `heed pass` and any `heed invariant` error.

`report` measures each instance with `pack_arena.py` (M2 rear blows and encircled share, M5
casualties, M6 duration) and from its heed log and uses:
  - first blows by a wolf on a subject (the first that reaches it in an engagement: 20 s), and
    of those the ones whose maker was not an individual to the subject when its windup began
    (in its sight but in its throng) or out of its sight then; per subject-minute;
  - repeated invisible blows: a blow whose maker had made contact within `heed_contact_s` before
    its windup began yet was not an individual then. Zero by construction (forced contact); the
    report asserts it, with the `heed invariant` lines;
  - later blows from someone unheeded after the contact window lapsed (allowed: reported);
  - reactions: blocks and dodges per wolf windup aimed at a subject (uses);
  - the subjects' own landed blows;
  - capacity: per subject its median and lowest, the share of passes at capacity, and the wound
    spiral (capacity lost against health lost, from `heed pass` lines).
Arms are `trial/variant`. With `--control`, the decision rule of docs/PACK_MIND.md §5.5: an arm
differs on a measure when its median lies outside the control's range and at least 2/3 of its
replicates do.
"""
import argparse
import json
import math
import re
import statistics
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pack_arena  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
TRIALS = ROOT / ".local/living/trials"
REPLICAS = "/home/spacetime/.local/share/spacetime/data/replicas"
ENGAGEMENT_S = 20.0
LINE = re.compile(r"heed (windup|blow|pass|invariant)[: ](.*)$")


def kv(text):
    return {k: v for k, v in re.findall(r"(\w+)=(\S+)", text)}


def collect(a):
    bdir = TRIALS / a.batch
    n = 0
    for d in sorted(p for p in bdir.iterdir() if p.is_dir() and (p / "state.json").exists()):
        st = json.loads((d / "state.json").read_text())
        rep = st.get("replica")
        if rep is None:
            print(f"{d.name}: no replica recorded", flush=True)
            continue
        r = subprocess.run(["docker", "exec", a.container, "sh", "-c", f"cat $(ls -1 {REPLICAS}/{rep}/module_logs/* | sort)"], capture_output=True, timeout=600)
        out = []
        for raw in r.stdout.decode("utf-8", "replace").splitlines():
            try:
                msg = json.loads(raw).get("message", "")
            except ValueError:
                msg = raw
            if "heed " in msg:
                out.append(msg)
        (d / "heed.log").write_text("\n".join(out) + ("\n" if out else ""))
        n += 1
        print(f"{d.name}: replica {rep}, {len(out)} heed lines", flush=True)
    print(f"collected {n} instances")


def med(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.median(xs), 4) if xs else None


def heed_lines(d):
    p = Path(d) / "heed.log"
    out = []
    if p.exists():
        for line in p.read_text().splitlines():
            m = LINE.search(line)
            if m:
                out.append((m.group(1), kv(m.group(2)), line))
    return out


def classify(outcome):
    o = outcome or ""
    if o.startswith("hit for"):
        return "hit"
    if o.startswith("blocked"):
        return "blocked"
    if "dodged" in o:
        return "dodged"
    if o.startswith("killed") or "killed" in o:
        return "hit"
    return "other"


def measure(d):
    run = pack_arena.load(d)
    base = pack_arena.measure(run)
    S, P, W = run["samples"], set(run["people"]), set(run["wolves"])
    out = {"dir": str(d), "arm": run["arm"], "variant": run["trial"]["variant"], "M2": base.get("M2", {}), "M5": base.get("M5", {}), "M6": base.get("M6", {}),
           "stopped_by": base.get("stopped_by"), "sample_hz": base.get("sample_hz")}
    if not S:
        return out
    # Subject-minutes from the first wolf windup at any subject to each subject's death or the end.
    wolf_on_people = [u for u in run["uses"] if u.get("actor") in W and u.get("target") in P and u.get("accepted_ms")]
    t_first = min((u["accepted_ms"] for u in wolf_on_people), default=None)
    end = S[-1]["ms"]
    minutes = 0.0
    if t_first is not None:
        for p in P:
            died = next((s["ms"] for s in S if p in s["dead"]), None)
            stop = min(end, died) if died else end
            minutes += max(0.0, (stop - t_first) / 60000)
    out["subject_minutes"] = round(minutes, 2)
    # Reactions: of the wolves' windups aimed at subjects, those blocked or dodged.
    outcomes = [classify(u.get("outcome")) for u in wolf_on_people]
    windups = len(wolf_on_people)
    reacted = sum(1 for o in outcomes if o in ("blocked", "dodged"))
    out["reactions"] = {"windups": windups, "blocked": outcomes.count("blocked"), "dodged": outcomes.count("dodged"), "hit": outcomes.count("hit"),
                        "per_windup": round(reacted / windups, 3) if windups else None}
    own = [u for u in run["uses"] if u.get("actor") in P and u.get("target") in W and u.get("accepted_ms")]
    out["subjects_blows"] = {"begun": len(own), "landed": sum(1 for u in own if classify(u.get("outcome")) == "hit")}
    # The heed log (heed arms only).
    lines = heed_lines(d)
    blows = [k for t, k, _ in lines if t == "blow" and int(k.get("v", 0)) in P and int(k.get("a", 0)) in W]
    windup_lines = [k for t, k, _ in lines if t == "windup" and int(k.get("v", 0)) in P and int(k.get("a", 0)) in W]
    invariants = [raw for t, _, raw in lines if t == "invariant"]
    firsts = [b for b in blows if b.get("first") == "1"]
    unheeded_first = [b for b in firsts if b.get("heeded_at_windup") == "0" and b.get("seen_at_windup") == "1"]
    unseen_first = [b for b in firsts if b.get("seen_at_windup") == "0"]
    repeat_invisible = [b for b in blows if b.get("repeat_in_window") == "1" and b.get("heeded_at_windup") == "0"]
    later_unheeded = [b for b in blows if b.get("first") == "0" and b.get("repeat_in_window") == "0" and b.get("heeded_at_windup") == "0"]
    per_min = lambda n: round(n / minutes, 3) if minutes > 0 else None
    landed = lambda bs: sum(1 for b in bs if b.get("out") == "hit")
    out["heed"] = {
        "logged": bool(lines),
        "blows": len(blows), "first_blows": len(firsts),
        "first_unheeded": len(unheeded_first), "first_unheeded_landed": landed(unheeded_first),
        "first_unseen": len(unseen_first),
        "first_unheeded_per_subject_min": per_min(len(unheeded_first)) if lines else (0.0 if minutes > 0 else None),
        "first_unheeded_share": round(len(unheeded_first) / len(firsts), 3) if firsts else (0.0 if not lines and windups else None),
        "repeat_invisible": len(repeat_invisible), "invariant_lines": len(invariants),
        "later_unheeded": len(later_unheeded),
        "windups_logged": len(windup_lines),
        "windups_heeded_share": round(sum(1 for w in windup_lines if w.get("heeded") == "1") / len(windup_lines), 3) if windup_lines else None,
    }
    # Capacity from the passes.
    passes = defaultdict(list)
    for t, k, _ in lines:
        if t == "pass" and int(k.get("id", 0)) in P:
            passes[int(k["id"])].append((int(k["cap"]), float(k["health"]), int(k["in_sight"]), int(k["picked"])))
    caps, at_cap, spiral = [], [], []
    for p, ps in passes.items():
        cs = [c for c, _, _, _ in ps]
        caps.append((statistics.median(cs), min(cs)))
        full = [1 for c, _, n, picked in ps if c > 0 and n > c and picked >= c]
        crowded = [1 for c, _, n, _ in ps if c > 0 and n > c]
        at_cap.append(len(full) / len(ps) if ps else None)
        start = cs[0] if cs and cs[0] > 0 else None
        low_h = min(h for _, h, _, _ in ps)
        if start:
            spiral.append({"cap_lost": round(1 - min(cs) / start, 3), "health_lost": round(1 - low_h, 3), "crowded_share": round(len(crowded) / len(ps), 3)})
    out["capacity"] = {"median": med([c for c, _ in caps]), "lowest": min((m for _, m in caps), default=None), "share_at_capacity": med(at_cap),
                       "spiral": spiral, "cap_lost_median": med([x["cap_lost"] for x in spiral]), "health_lost_median": med([x["health_lost"] for x in spiral])}
    return out


KEYS = [("heed", "first_unheeded_per_subject_min"), ("heed", "first_unheeded_share"), ("heed", "first_unseen"), ("heed", "later_unheeded"),
        ("heed", "windups_heeded_share"), ("M2", "rear_blow_share"), ("M2", "encircled_share_k3"), ("reactions", "per_windup"),
        ("subjects_blows", "landed"), ("M5", "people_dead"), ("M5", "wolves_dead"), ("M5", "people_health_lost"), ("M5", "wolf_health_lost"),
        ("M6", "duration_s"), ("capacity", "median"), ("capacity", "share_at_capacity"), ("capacity", "cap_lost_median"), ("capacity", "health_lost_median")]


def table(results):
    by = defaultdict(list)
    for r in results:
        by[r["arm"]].append(r)
    t = {}
    for arm, rs in by.items():
        row = {"n": len(rs), "dirs": [r["dir"] for r in rs]}
        for m, k in KEYS:
            vals = [r.get(m, {}).get(k) for r in rs]
            have = [v for v in vals if v is not None]
            row[f"{m}.{k}"] = {"median": med(have), "min": min(have) if have else None, "max": max(have) if have else None, "values": vals}
        row["repeat_invisible_total"] = sum(r.get("heed", {}).get("repeat_invisible", 0) for r in rs)
        row["invariant_lines_total"] = sum(r.get("heed", {}).get("invariant_lines", 0) for r in rs)
        t[arm] = row
    return t


def report(a):
    dirs = list(pack_arena.instances(a.dirs))
    results = [measure(d) for d in dirs]
    t = table(results)
    out = {"instances": results, "arms": t}
    if a.control:
        out["differs_from_control"] = pack_arena.decide(t, a.control)
    bad = sum(r["repeat_invisible_total"] + r["invariant_lines_total"] for r in t.values())
    out["repeat_invisible_assert"] = "ok: 0" if bad == 0 else f"FAILED: {bad}"
    for arm, row in sorted(t.items()):
        print(f"\n== {arm} (n={row['n']}; repeated invisible blows {row['repeat_invisible_total']}, invariant lines {row['invariant_lines_total']})")
        for m, k in KEYS:
            v = row[f"{m}.{k}"]
            flag = ""
            if a.control and arm in out["differs_from_control"] and out["differs_from_control"][arm].get(f"{m}.{k}"):
                flag = "  DIFFERS"
            print(f"  {m}.{k:34s} median {v['median']!s:>8}  range {v['min']!s}..{v['max']!s}{flag}")
    print(f"\nrepeated invisible blows (must be 0): {out['repeat_invisible_assert']}")
    if a.json:
        Path(a.json).write_text(json.dumps(out, indent=1))
        print("wrote", a.json)
    return 0 if bad == 0 else 1


def selftest(_a=None):
    ok = True

    def check(name, cond, got):
        nonlocal ok
        print(("PASS " if cond else "FAIL ") + name, "" if cond else got)
        ok = ok and cond
    k = kv("a=12 v=7 out=hit first=1 repeat_in_window=0 seen_at_windup=1 heeded_at_windup=0 windup_ms=350 cap=4 health=0.900")
    check("a blow line parses", k["a"] == "12" and k["heeded_at_windup"] == "0" and k["out"] == "hit", k)
    m = LINE.search("2026-11-22T02:42:00Z  INFO: tick authority/src/heed.rs:415: heed windup a=269 v=268 seen=1 heeded=1 contact=1 cap=0")
    check("a module log line is found", m and m.group(1) == "windup" and kv(m.group(2))["contact"] == "1", m)
    m = LINE.search("ERROR: heed invariant: a blow by #3 reached #4 after contact")
    check("an invariant line is found", m and m.group(1) == "invariant", m)
    check("outcomes classify", [classify(x) for x in ("hit for 7", "blocked, 2 got through", "dodged", "missed")] == ["hit", "blocked", "dodged", "other"], None)
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect")
    c.add_argument("--batch", required=True)
    c.add_argument("--container", default="slop-heede4-trials")
    c.set_defaults(f=collect)
    r = sub.add_parser("report")
    r.add_argument("dirs", nargs="+")
    r.add_argument("--control")
    r.add_argument("--json")
    r.set_defaults(f=report)
    sub.add_parser("selftest").set_defaults(f=selftest)
    a = ap.parse_args()
    return a.f(a) or 0


if __name__ == "__main__":
    raise SystemExit(main())
