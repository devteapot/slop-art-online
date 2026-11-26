#!/usr/bin/env python3
"""Who each character's `familiar` rows are of (familiar-cap, docs/BOUNDED_RETENTION.md §3.1):
per observer, its rows by what they are (regions, structures, artifacts, creatures) and its
creature rows by how it stands with them, in the order `brain::prune_familiar` spares them under
the `familiar_regard` law: family (a parent, a child, the other parent of one's child), community
(a shared membership), acquaintance (told the name), relation (a `relation` or `relation_fight`
row: the mind has feelings about them or said whom it fights) and, none of these, an unnamed
stranger (a person or an animal; alive or dead). The same test as `perception::knows_name_fresh`
plus the relation rows. Read only; owner SQL through the verify harness.

    familiar_census.py (--run <verify run> | --db <database>) [--label NAME] [--out FILE]

Prints per observer kind the distribution of rows per observer (p50, p90, p99, max), the share of
each class, and how many observers hold more than 64 … 2,048 rows in all and in strangers; writes
the whole census (per observer) as JSON to `--out` (default `<run>/familiar-census-<label>.json`).
"""
import argparse
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / ".agents/skills/verify/scripts"))
import verify as V  # noqa: E402

FAM = {1: "region", 2: "creature", 3: "structure", 4: "artifact"}
CLASSES = ("family", "community", "acquaintance", "relation", "stranger_person", "stranger_animal")
THRESHOLDS = (64, 128, 192, 256, 384, 512, 1024, 2048)


def sql_rows(db, token, query):
    """Owner SQL over HTTP (the verify harness's server: LIVING_STDB_URL), rows as dicts."""
    code, body = V.http(f"/v1/database/{db}/sql", query, token, raw=True, timeout=120)
    if code != 200:
        raise RuntimeError(f"sql {code}: {body[:200]}")
    res = json.loads(body)[-1]
    names = [e["name"].get("some", "?") for e in res["schema"]["elements"]]
    return [dict(zip(names, r)) for r in res["rows"]]


def pct(xs, p):
    if not xs:
        return 0
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(p / 100 * (len(xs) - 1))))]


def census(rows, chars, members, acq, rel):
    per = defaultdict(Counter)
    for r in rows:
        o, thing = r["actor"], int(r["thing"])
        kind, t = FAM.get(thing >> 40, "other"), thing & ((1 << 40) - 1)
        if kind != "creature":
            per[o][kind] += 1
            continue
        oc, tc = chars.get(o), chars.get(t)
        if oc is None or tc is None:
            per[o]["stranger_animal"] += 1
            continue
        family = oc["parent_a"] == t or oc["parent_b"] == t or tc["parent_a"] == o or tc["parent_b"] == o or (o, t) in rel["coparent"]
        if family:
            c = "family"
        elif members.get(o) is not None and members.get(o) == members.get(t):
            c = "community"
        elif (o, t) in acq:
            c = "acquaintance"
        elif (o, t) in rel["pairs"]:
            c = "relation"
        else:
            c = "stranger_person" if tc["kind"] == "person" else "stranger_animal"
        per[o][c] += 1
        if not tc["alive"]:
            per[o]["of_dead"] += 1
    return per


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", help="a verify run (its database and evidence folder)")
    ap.add_argument("--db", help="a database by name instead (evidence under .local/living/verify/<db>)")
    ap.add_argument("--label", default=time.strftime("%H%M%S"))
    ap.add_argument("--out")
    a = ap.parse_args()
    db = V.load(a.run)["db"] if a.run else a.db
    rid = a.run or db
    token = V.admin_token()
    sql = lambda s: sql_rows(db, token, s)  # noqa: E731
    rows = sql("SELECT actor, thing FROM familiar")
    chars = {c["id"]: c for c in sql("SELECT id, kind, alive, ai, parent_a, parent_b FROM character")}
    members = {m["member"]: m["community"] for m in sql("SELECT member, community FROM membership")}
    acq = {(r["observer"], r["known"]) for r in sql("SELECT observer, known FROM acquaintance")}
    pairs = {(r["actor"], r["other"]) for r in sql("SELECT actor, other FROM relation")}
    pairs |= {(r["actor"], r["other"]) for r in sql("SELECT actor, other FROM relation_fight")}
    coparent = set()
    for c in chars.values():
        if c["parent_a"] and c["parent_b"]:
            coparent |= {(c["parent_a"], c["parent_b"]), (c["parent_b"], c["parent_a"])}
    sex_seen = len(sql("SELECT id FROM sex_seen"))
    per = census(rows, chars, members, acq, {"pairs": pairs, "coparent": coparent})
    report = {"run": rid, "label": a.label, "rows": len(rows), "sex_seen": sex_seen, "observers": len(per), "by_kind": {}}
    groups = defaultdict(list)
    for o, cnt in per.items():
        oc = chars.get(o, {"kind": "?", "alive": False})
        groups[f"{oc['kind']}{'' if oc['alive'] else ' (dead)'}"].append((o, cnt))
    for g, items in sorted(groups.items()):
        totals = [sum(v for k, v in c.items() if k != "of_dead") for _, c in items]
        strangers = [c["stranger_person"] + c["stranger_animal"] for _, c in items]
        spared = [sum(c[k] for k in ("family", "community", "acquaintance", "relation")) for _, c in items]
        share = Counter()
        for _, c in items:
            share.update({k: v for k, v in c.items()})
        n = max(1, sum(totals))
        report["by_kind"][g] = {
            "observers": len(items), "rows": sum(totals),
            "per_observer": {"p50": pct(totals, 50), "p90": pct(totals, 90), "p99": pct(totals, 99), "max": max(totals)},
            "strangers_per_observer": {"p50": pct(strangers, 50), "p90": pct(strangers, 90), "p99": pct(strangers, 99), "max": max(strangers)},
            "spared_per_observer": {"p50": pct(spared, 50), "p90": pct(spared, 90), "p99": pct(spared, 99), "max": max(spared)},
            "share": {k: round(share[k] / n, 4) for k in sorted(share)},
            "over": {str(t): sum(1 for x in totals if x > t) for t in THRESHOLDS},
            "strangers_over": {str(t): sum(1 for x in strangers if x > t) for t in THRESHOLDS},
            "rows_over": {str(t): sum(max(0, x - t) for x in totals) for t in THRESHOLDS},
        }
    report["per_observer"] = {str(o): dict(c) for o, c in per.items()}
    out = Path(a.out) if a.out else ROOT / ".local/living/verify" / rid / f"familiar-census-{a.label}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k != "per_observer"}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
