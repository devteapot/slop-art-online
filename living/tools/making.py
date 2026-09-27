#!/usr/bin/env python3
"""Do people make things? Intentions, decided acts and their outcomes, and what exists.

From the model journal of a run (`.local/living/journal/<run>/`, gzipped or not):
- acts decided in deliberations and conversation turns, by skill and item;
- outcomes of decided acts as the minds later read them ("You did what you had decided: …",
  "What you had decided did not work out: …: why"), by skill and reason;
- how often thoughts mention making (craft, build, make, a cloak, a spear, …).
From the database: successful skill uses (practice) grouped as gathering, making and other,
structures by kind, and made goods held or stored.

Usage: living/tools/making.py <db> <run>
"""
import collections
import gzip
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STDB = str(ROOT / "living/tools/stdb")
GATHER = {"gather", "graze", "clear", "take", "store", "drop"}
MAKE = {"craft", "build", "cook", "smoke", "plant", "pave", "write", "tan"}
MADE = {"spear", "cloak", "torch", "axe", "pick", "net", "basket", "bow", "arrow", "salve", "leather", "armor", "cooked_meat", "cooked_fish", "smoked_fish", "tablet"}
WORDS = re.compile(r"\b(craft|crafting|build|building|make|making|made|spear|cloak|torch|net|basket|bow|arrows?|salve|leather|armor|shelter|house|storage)\b", re.I)
OUTCOME = re.compile(r"(You did what you had decided|What you had decided did not work out): ([^\n\"]*)")


def rows(db, q):
    out = subprocess.run([STDB, "sql", "-s", "local", db, q], capture_output=True, text=True).stdout
    lines = [l for l in out.splitlines() if "|" in l and not l.strip().startswith("-")]
    if not lines:
        return []
    head = [h.strip() for h in lines[0].split("|")]
    return [dict(zip(head, [v.strip().strip('"') for v in l.split("|")])) for l in lines[1:]]


def entries(run):
    for f in sorted((ROOT / ".local/living/journal" / run).glob("*.jsonl*")):
        with (gzip.open(f, "rt") if f.suffix == ".gz" else open(f)) as fh:
            for line in fh:
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue


def act_key(a):
    skill = a.get("do") if isinstance(a.get("do"), str) else (a.get("do") or {}).get("skill", "?")
    item = a.get("item") or (a.get("do") or {}).get("item") if isinstance(a.get("do"), dict) else a.get("item")
    return skill, item


def main():
    db, run = sys.argv[1], sys.argv[2]
    decided = collections.Counter()
    outcomes = collections.Counter()
    seen_outcomes = set()
    thoughts = mentions = 0
    for e in entries(run):
        if e.get("error"):
            continue
        if e["purpose"] in ("deliberate", "talk"):
            try:
                reply = json.loads(e["reply"])
            except (json.JSONDecodeError, TypeError):
                reply = {}
            for a in reply.get("acts") or []:
                if isinstance(a, dict):
                    decided[act_key(a)] += 1
        if e["purpose"] == "think":
            thoughts += 1
            mentions += bool(WORDS.search(e.get("reply") or ""))
        # Outcomes are read in later prompts; count each distinct one per actor once.
        if e["purpose"] in ("think", "deliberate"):
            text = "\n".join(m.get("content", "") for m in e["request"].get("messages", []))
            for kind, what in OUTCOME.findall(text):
                if (e["actor"], what) in seen_outcomes:
                    continue
                seen_outcomes.add((e["actor"], what))
                ok = kind.startswith("You did")
                skill = what.split()[0].strip(":,.").lower() if what else "?"
                why = "" if ok else (what.split(": ", 1)[1][:70] if ": " in what else what[:70])
                outcomes[(skill, "done" if ok else "failed", why)] += 1
    print(f"== {db} / {run}")
    print(f"thoughts mentioning making: {mentions} of {thoughts}")
    make_acts = {k: n for k, n in decided.items() if k[0] in MAKE}
    print(f"acts decided: {sum(decided.values())}; making acts: {sum(make_acts.values())}")
    for (skill, item), n in sorted(make_acts.items(), key=lambda kv: -kv[1])[:15]:
        print(f"   {n:4d}  {skill} {item or ''}")
    print("   other acts:", dict(collections.Counter({k[0]: n for k, n in decided.items() if k[0] not in MAKE}).most_common(10)))
    print("outcomes of decided acts (distinct per person):")
    for (skill, res, why), n in sorted(outcomes.items(), key=lambda kv: -kv[1])[:20]:
        print(f"   {n:4d}  {skill:8s} {res:6s} {why}")
    kinds = {r["id"]: r["kind"] for r in rows(db, "SELECT id, kind FROM character")}
    use = collections.Counter()
    for p in rows(db, "SELECT actor, skill, uses FROM practice"):
        if kinds.get(p["actor"]) == "person":
            g = "gathering" if p["skill"] in GATHER else "making" if p["skill"] in MAKE else "other"
            use[g] += int(p["uses"])
            if g == "making":
                use["making:" + p["skill"]] += int(p["uses"])
    print("practice of the living (successful uses):", dict(use))
    print("structures:", dict(collections.Counter(s["kind"] for s in rows(db, "SELECT id, kind FROM structure"))))
    made = collections.Counter()
    for r in rows(db, "SELECT owner, item, qty FROM inventory"):
        if r["item"] in MADE:
            made[r["item"]] += int(r["qty"])
    print("made goods held or stored:", dict(made))


if __name__ == "__main__":
    main()
