#!/usr/bin/env python3
"""How knowledge moves through a lab's people, from their minds (read-only, for developers;
nothing here reaches a mind):

- provenance: each held belief as lived, hearsay (one teller), corroborated (two or more
  tellers, never lived) or unattributed (written before provenance was recorded);
- stories: kept memories and the beliefs they ground (`GROUNDS`);
- hardening: how far stances lean, how many are near-absolute, and what backs them;
- shared belief: per community, what most members hold in common, and how much of it
  newcomers (joined after the founding, or born since) hold;
- offices: roles the minds themselves name (no engine role exists).

  living/tools/transmission.py aske-coast-6 --run aske-coast-6
  living/tools/transmission.py aske-coast-6 --run aske-coast-6 --json out.json

Neo4j is queried with cypher-shell inside its container (the container's own auth env; no
password on the command line).
"""
import argparse
import collections
import csv
import io
import json
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STDB = str(ROOT / "living/tools/stdb")
# Structure, not belief (as in living/mind/src/memory.rs, without FEELS/JUDGES).
STRUCTURE = ["KNOWS", "FEELS", "WAS", "INVOLVES", "GROUNDS", "CHILD_OF", "PARENT_OF", "MERGED_INTO"]
ANCHORS = ("person:", "place:", "kind:", "know:", "stance:")
OFFICE = re.compile(r"\b(role|office|chief|head(wo)?man|headman|elder|keeper|council|leader|lead|warden|watch(man)?|healer|smith|priest|judge|oath|tally|steward)\b", re.I)


def rows(db, q):
    out = subprocess.run([STDB, "sql", "-s", "local", db, q], capture_output=True, text=True).stdout
    lines = [l for l in out.splitlines() if "|" in l and not l.strip().startswith("-")]
    if not lines:
        return []
    head = [h.strip() for h in lines[0].split("|")]
    return [{h: v.strip().strip('"') for h, v in zip(head, l.split("|"))} for l in lines[1:]]


class Graph:
    def __init__(self, container, engine, run):
        self.args = [engine, "exec", "-i", container, "sh", "-c",
                     'NEO4J_PASSWORD="${NEO4J_AUTH#*/}" cypher-shell -a bolt://localhost:7687 -u neo4j --format plain']
        self.run = json.dumps(run)

    def q(self, text):
        r = subprocess.run(self.args, input=text.replace("$run", self.run), capture_output=True, text=True, timeout=300)
        if r.returncode:
            raise SystemExit(f"cypher failed: {r.stderr.strip()[:400]}")
        lines = [l for l in r.stdout.splitlines() if l.strip()]
        if not lines:
            return []
        table = list(csv.reader(io.StringIO("\n".join(lines)), skipinitialspace=True))
        return [dict(zip(table[0], row)) for row in table[1:]]


def num(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def report(args):
    people = {int(c["id"]): c for c in rows(args.db, "SELECT id, name, kind, alive, stage, born_ms FROM character") if c["kind"] == "person" and c["alive"] == "true"}
    communities = {int(c["id"]): c for c in rows(args.db, "SELECT id, name, founded_ms FROM community")}
    member = {int(m["member"]): (int(m["community"]), int(m["since_ms"])) for m in rows(args.db, "SELECT community, member, since_ms FROM membership")}
    g = Graph(args.container, args.engine, args.run)
    alive = sorted(people)
    ids = json.dumps(alive)

    # Provenance of held beliefs (FEELS and structure excluded; stances included).
    prov = collections.defaultdict(collections.Counter)
    for r in g.q(f"""MATCH (s:Concept {{run: $run}})-[r {{open: true}}]->(:Concept)
        WHERE s.actor IN {ids} AND NOT type(r) IN {json.dumps(STRUCTURE)}
        RETURN s.actor AS actor,
               CASE WHEN r.firsthand THEN 'lived' WHEN r.sources IS NULL THEN 'unattributed'
                    WHEN size(r.sources) >= 2 THEN 'corroborated' WHEN size(r.sources) = 1 THEN 'hearsay' ELSE 'unattributed' END AS kind,
               count(*) AS n"""):
        prov[int(r["actor"])][r["kind"]] += int(r["n"])
    total = collections.Counter()
    for c in prov.values():
        total.update(c)

    # Stories and what they ground.
    mem = {int(r["actor"]): r for r in g.q(f"""MATCH (m:Concept:Memory {{run: $run}}) WHERE m.actor IN {ids} AND NOT m:Forgotten
        OPTIONAL MATCH (m)-[g:GROUNDS {{open: true}}]->()
        WITH m, count(g) AS grounds
        RETURN m.actor AS actor, count(m) AS memories, sum(CASE WHEN grounds > 0 THEN 1 ELSE 0 END) AS grounding,
               sum(CASE WHEN m.childhood THEN 1 ELSE 0 END) AS childhood""")}

    # Stances: lean, near-absolute ones, and their backing.
    stances = g.q(f"""MATCH (s:Concept {{run: $run, key: 'self'}})-[r:JUDGES {{open: true}}]->(j:Concept)
        WHERE s.actor IN {ids}
        OPTIONAL MATCH (m:Memory)-[:GROUNDS {{open: true}}]->(j) WHERE m.run = $run AND m.actor = s.actor AND NOT m:Forgotten
        WITH s, r, j, count(m) AS stories
        RETURN s.actor AS actor, j.key AS key, toFloat(coalesce(r.value, 0.5)) AS value, coalesce(r.hearsay, false) AS hearsay,
               coalesce(r.firsthand, false) AS lived, coalesce(size(r.because), 0) AS evidence, stories""")
    leans = [abs(num(s["value"], 0.5) - 0.5) for s in stances]
    absolute = [s for s in stances if abs(num(s["value"], 0.5) - 0.5) >= 0.4]

    # Shared belief per community: (from, rel, to) over anchors, stances by side.
    held = collections.defaultdict(set)
    for r in g.q(f"""MATCH (a:Concept {{run: $run}})-[r {{open: true}}]->(b:Concept)
        WHERE a.actor IN {ids} AND NOT type(r) IN {json.dumps(STRUCTURE)}
          AND (a.key = 'self' OR any(p IN {json.dumps(list(ANCHORS))} WHERE a.key STARTS WITH p))
          AND any(p IN {json.dumps(list(ANCHORS))} WHERE b.key STARTS WITH p)
        RETURN DISTINCT a.actor AS actor, a.key AS a, coalesce(r.rel, type(r)) AS rel, b.key AS b,
               CASE WHEN type(r) = 'JUDGES' THEN CASE WHEN toFloat(coalesce(r.value, 0.5)) >= 0.5 THEN 'for' ELSE 'against' END ELSE '' END AS side"""):
        held[(r["a"], r["rel"], r["b"], r["side"])].add(int(r["actor"]))
    shared = {}
    for cid, c in communities.items():
        members = [p for p in alive if member.get(p, (None,))[0] == cid]
        if len(members) < 2:
            continue
        founded = num(c["founded_ms"])
        newcomer = [p for p in members if member[p][1] > founded + 600_000 or num(people[p]["born_ms"]) > founded]
        old = [p for p in members if p not in newcomer]
        base = old if len(old) >= 2 else members
        need = max(2, (len(base) + 1) // 2)
        common = [(k, v) for k, v in held.items() if len(v & set(base)) >= need]
        common.sort(key=lambda kv: -len(kv[1] & set(members)))
        reach = [len(v & set(newcomer)) / len(newcomer) for _, v in common] if newcomer else []
        shared[c["name"]] = {
            "members": len(members), "newcomers": len(newcomer), "beliefs_held_by_most": len(common),
            "newcomer_share": round(sum(reach) / len(reach), 3) if reach else None,
            "top": [{"belief": " ".join(x for x in k if x), "holders": len(v & set(members))} for k, v in common[:args.top]],
        }

    # Offices the minds name.
    offices = collections.defaultdict(lambda: collections.defaultdict(set))
    for r in g.q(f"""MATCH (c:Concept {{run: $run}}) WHERE c.actor IN {ids} AND NOT c:Memory AND NOT c:Merged
        WITH c, c.key + ' ' + coalesce(c.name, '') + ' ' + reduce(s = '', l IN labels(c) | s + ' ' + l) AS text
        WHERE text =~ '(?i).*\\\\b(role|office|chief|headwoman|headman|elder|keeper|council|leader|warden|healer|priest|judge|oath|tally|steward).*'
        RETURN c.actor AS actor, c.key AS key, coalesce(c.name, c.key) AS name"""):
        word = OFFICE.search(r["key"] + " " + r["name"])
        if word:
            cid = member.get(int(r["actor"]), (None,))[0]
            offices[communities[cid]["name"] if cid in communities else "(none)"][word.group(0).lower()].add(int(r["actor"]))

    out = {
        "db": args.db, "run": args.run, "people": len(alive),
        "provenance": dict(total),
        "stories": {"memories": sum(int(r["memories"]) for r in mem.values()), "grounding": sum(int(r["grounding"]) for r in mem.values()),
                    "childhood": sum(int(r["childhood"]) for r in mem.values())},
        "stances": {"held": len(stances), "mean_lean": round(sum(leans) / len(leans), 3) if leans else None, "near_absolute": len(absolute),
                    "near_absolute_hearsay": sum(1 for s in absolute if s["hearsay"] == "TRUE" or s["hearsay"] == "true"),
                    "near_absolute_with_story": sum(1 for s in absolute if int(s["stories"]) > 0)},
        "communities": shared,
        "offices": {c: {w: len(a) for w, a in sorted(ws.items(), key=lambda x: -len(x[1]))} for c, ws in offices.items()},
    }
    return out


def show(r):
    print(f"== {r['db']} (minds of run {r['run']}): {r['people']} people alive")
    p = r["provenance"]
    n = sum(p.values()) or 1
    print("beliefs held: " + ", ".join(f"{k} {v} ({100 * v / n:.0f}%)" for k, v in sorted(p.items(), key=lambda x: -x[1])))
    s = r["stories"]
    print(f"memories {s['memories']} ({s['childhood']} from childhood), {s['grounding']} grounding a belief")
    t = r["stances"]
    print(f"stances {t['held']}, mean lean {t['mean_lean']}; near-absolute {t['near_absolute']} "
          f"({t['near_absolute_hearsay']} hearsay, {t['near_absolute_with_story']} with a story behind them)")
    for name, c in r["communities"].items():
        share = "n/a" if c["newcomer_share"] is None else f"{100 * c['newcomer_share']:.0f}%"
        print(f"-- {name}: {c['members']} members ({c['newcomers']} newcomers); {c['beliefs_held_by_most']} beliefs held by most; newcomers hold {share} of them")
        for b in c["top"]:
            print(f"     {b['holders']:>3}  {b['belief']}")
    for name, ws in r["offices"].items():
        print(f"-- offices named in {name}: " + ", ".join(f"{w} ({n} minds)" for w, n in ws.items()))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("db", help="SpacetimeDB database")
    ap.add_argument("--run", help="mind run name in Neo4j (default: the database name)")
    ap.add_argument("--container", default="sao-living-neo4j-2", help="Neo4j container (default: Neo4j B)")
    ap.add_argument("--engine", default=shutil.which("docker") and "docker" or "podman", help="container CLI (podman on the Fedora host)")
    ap.add_argument("--top", type=int, default=8)
    ap.add_argument("--json", help="also write the figures here (for comparing labs)")
    args = ap.parse_args()
    args.run = args.run or args.db
    r = report(args)
    show(r)
    if args.json:
        Path(args.json).write_text(json.dumps(r, indent=2))


if __name__ == "__main__":
    main()
