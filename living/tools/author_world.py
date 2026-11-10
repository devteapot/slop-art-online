#!/usr/bin/env python3
"""Draft and compile an authored world: character sheets from a world bible and a cast list.

Input: `living/seeds/worlds/<world>/bible.md`, `living/seeds/worlds/<world>/cast.json` and
`living/seeds/worlds/<world>/seed.json` (map, pace, habits, animals, setting). Which model each
settlement thinks with is set in the models config (`groups`), not here.
For each household a model drafts one sheet per member (identity, relations, memories,
stances, a secret if any) against the bible and the whole cast. A household sees only its
own members' secrets, so sheets cannot leak what others hide. Every sheet is checked: people
named must be in the cast, numbers in range, and family ties mutual (missing ones are
drafted in a second pass). Sheets are cached per household (`sheets/<key>.json`), so a rerun
only drafts what is missing; delete a file to redraft that household.

Output: `living/seeds/<world>.json`, a seed with authored `residents` per settlement.

A world directory with `world.json` instead is planned and merged into an existing seed (the
island's seeded lives, docs/SEEDED_LIVES.md): households and situations are drafted around the
anchor people world.json fixes, sheets per household with the situations they are in, ties made
mutual, references checked against the rules' catalog, a review pass by a second model, and the
result written into `living/seeds/<into>.json`. Spend is logged to `authoring-log.jsonl`.

Usage: living/tools/author_world.py <world> [--profile glm-flash] [--jobs 4] [--compile-only]
       living/tools/author_world.py island --profile deepseek-flash --only Brackenford \
           --review glm-flash --review-effort high --redraft
The model is called through the mind's model config (`LIVING_MODELS` or
`living/configs/models.json`) with keys from `.env`; nothing secret is printed.
"""
import argparse
import concurrent.futures
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TRAITS = ["caution", "sociability", "empathy", "curiosity", "ambition", "introspection", "temper", "nurture"]
FAMILY = re.compile(r"\b(mother|father|son|daughter|sister|brother|wife|husband|partner|grand(mother|father|son|daughter)|aunt|uncle|nephew|niece|cousin|twin|apprentice|master)\b", re.I)


def env():
    vals = dict(os.environ)
    for f in [ROOT / ".env", ROOT / ".local/living/neo4j.env"]:
        if f.exists():
            for line in f.read_text().splitlines():
                if "=" in line and not line.lstrip().startswith("#"):
                    k, v = line.split("=", 1)
                    vals.setdefault(k.strip(), v.strip().strip('"'))
    return vals


def model_call(profile_name, system, user, effort="medium", tries=4):
    e = env()
    models = json.loads(Path(e.get("LIVING_MODELS", ROOT / "living/configs/models.json")).read_text())
    p = models["profiles"][profile_name]
    body = {"model": p["model"], "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    if p.get("reasoning_effort"):
        body["reasoning_effort"] = effort
    req = urllib.request.Request(p["base_url"].rstrip("/") + "/chat/completions", data=json.dumps(body).encode(), headers={"Content-Type": "application/json", "Authorization": "Bearer " + e[p["key_env"]]})
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=600) as r:
                v = json.loads(r.read())
            text = v["choices"][0]["message"]["content"]
            text = text if isinstance(text, str) else "".join(x.get("text", "") for x in text)
            m = re.search(r"\{.*\}", text, re.S)
            return json.loads(m.group(0))
        except Exception as ex:  # noqa: BLE001 - retried, then reported
            if attempt == tries - 1:
                raise RuntimeError(f"model call failed: {ex}") from ex
            time.sleep(5 * (attempt + 1))


def people_of(cast):
    for s in cast["settlements"]:
        for h in s["households"]:
            for m in h["members"]:
                yield s, h, m


def public_ties(m):
    return [t for t in m.get("ties", []) if not t.startswith("SECRET")]


def roster(cast):
    lines = []
    for s, h, m in people_of(cast):
        lines.append(f"- {m['name']} ({m['age']:g}, {m['sex']}, {s['name']}, household {h['key']}): {m['role']}. Ties: {'; '.join(public_ties(m))}")
    return "\n".join(lines)


SYSTEM = """You write character sheets for the people of a persistent simulated world. Each sheet is who that person is at the moment the world begins: their own voice, temperament, loves, grudges, memories and beliefs. What happens next is not written: never script their future.

Rules:
- Stay consistent with the world bible and the cast. Name only people who are in the cast, spelled exactly. Dead people (like Tomas) may appear in memories and stances but never in relations.
- A person knows only what they could know. Other people's secrets are hidden from you unless the person below holds them. A person's own secret goes in "secret" and may colour their memories and stances, but they would not say it aloud.
- Relations: everyone named in their ties, plus a few others they would plausibly have feelings about (neighbours, rivals, trade partners), 4-12 in all for adults, 2-5 for children. trust and affinity range from -100 to 100. The label is a short word (sister, friend, rival, creditor, apprentice, stranger). The note is one line in their words.
- Memories: 3-6 concrete events from their life, in their own words (older people remember the Hunger Winter or the Oath; others last winter, trade days, Tomas's death, small family moments). Salience ranges from 0 to 1. "about" lists the cast members involved.
- Stances: 3-6 beliefs they act on, as snake_case keys with a value from 0 to 1 (how strongly held) and a reason.
- Traits (0-100): caution, sociability, empathy, curiosity, ambition, introspection, temper, nurture. Vary them: not everyone is kind or calm.
- Offices, trades, standing and money are part of who people are: an office holder knows their duties and rights and how others see them; masters, apprentices and hired hands know who they work for and what they are paid; people know roughly how many marks they have and what things cost. Other people know who holds which office.
- Babies and small children: a short simple narrative (a baby's is sensation), a few relations to family, one or two memories at most, no stances.

Reply with ONE JSON object: {"sheets": {"<name>": {"narrative": "first person, 2-5 sentences", "values": [...], "goals": [...], "mood": "...", "traits": {...}, "relations": [{"name": "...", "trust": 0, "affinity": 0, "label": "...", "note": "..."}], "memories": [{"gist": "...", "salience": 0.5, "about": ["..."]}], "stances": [{"key": "...", "value": 0.8, "why": "..."}], "secret": "... or empty"}}}"""


def draft_household(world_dir, cast, bible, s, h, profile):
    members = "\n".join(
        f"- {m['name']} ({m['age']:g}, {m['sex']}), {m['role']}. Knows: {', '.join(m['knows']) or 'nothing yet'}. Ties: {'; '.join(m.get('ties', []))}" for m in h["members"]
    )
    user = f"""# World bible
{bible}

# The whole cast (public knowledge)
{roster(cast)}

# Write sheets for this household of {s['name']} ({h['key']})
{members}

Write one sheet for each of: {', '.join(m['name'] for m in h['members'])}."""
    v = model_call(profile, SYSTEM, user)
    return v.get("sheets", v)


def clamp(x, lo, hi, default):
    try:
        return max(lo, min(hi, float(x)))
    except (TypeError, ValueError):
        return default


def check_sheet(name, sheet, names, notes):
    out = {"narrative": str(sheet.get("narrative", "")).strip()}
    if not out["narrative"]:
        notes.append(f"{name}: no narrative")
    for k in ["values", "goals"]:
        out[k] = [str(x) for x in sheet.get(k, []) if str(x).strip()][:8]
    out["mood"] = str(sheet.get("mood", "settled"))
    out["traits"] = {t: round(clamp(sheet.get("traits", {}).get(t), 0, 100, 50)) for t in TRAITS}
    rels, seen = [], set()
    for r in sheet.get("relations", []):
        n = r.get("name")
        # Epithets the bible uses ("Old Aud") name the same person.
        if n not in names and isinstance(n, str) and n.split(" ", 1)[-1] in names:
            n = n.split(" ", 1)[-1]
        if n not in names or n == name or n in seen:
            notes.append(f"{name}: relation to unknown or repeated '{n}' dropped")
            continue
        seen.add(n)
        rels.append({"name": n, "trust": round(clamp(r.get("trust"), -100, 100, 0)), "affinity": round(clamp(r.get("affinity"), -100, 100, 0)), "label": str(r.get("label", "acquaintance"))[:32], "note": str(r.get("note", ""))[:240]})
    out["relations"] = rels
    out["memories"] = [
        {"gist": str(m.get("gist", ""))[:400], "salience": round(clamp(m.get("salience"), 0, 1, 0.5), 2), "about": [a for a in m.get("about", []) if a in names and a != name]}
        for m in sheet.get("memories", [])
        if str(m.get("gist", "")).strip()
    ][:8]
    out["stances"] = [
        {"key": re.sub(r"[^a-z0-9_]", "_", str(st.get("key", "")).lower()).strip("_")[:48], "value": round(clamp(st.get("value"), 0, 1, 0.7), 2), "why": str(st.get("why", ""))[:240]}
        for st in sheet.get("stances", [])
        if st.get("key")
    ][:8]
    secret = str(sheet.get("secret", "") or "").strip()
    if secret:
        out["secret"] = secret[:400]
    return out


# ---- seeded lives: a world planned in world.json and drafted into an existing seed ------------
#
# docs/SEEDED_LIVES.md. A world directory with `world.json` is planned, not cast by hand:
# 1. cast: per settlement, a model drafts its households around the anchor people world.json
#    fixes (the people the world tensions hang on), and the settlement's own situations (a debt,
#    a courtship, a feud ...), each with every side's view;
# 2. sheets: per household, as above, with the situations its members are part of;
# 3. checks: names, kin, ties felt both ways (missing sides drafted), know-how and items that
#    exist in the rules (`living/rules/src/catalog.rs`), occupations that have starting ways;
# 4. review: per settlement, a second model reads each situation against its people's sheets
#    and names contradictions; flagged households are redrafted once with the notes;
# 5. compile: residents, stores, ledgers and ways merged into `living/seeds/<into>.json`.
# Every model call's tokens go to `authoring-log.jsonl` in the world directory (the spend).

import threading

LOG_LOCK = threading.Lock()
LOG_PATH = None
SLUG = re.compile(r"[^a-z0-9]+")


def slug(s):
    return SLUG.sub("-", s.lower()).strip("-")


def logged_call(profile_name, system, user, effort, purpose, tries=4, max_tokens=None):
    """model_call with the effort given as is (None: not sent) and the usage logged."""
    e = env()
    models = json.loads(Path(e.get("LIVING_MODELS", ROOT / "living/configs/models.json")).read_text())
    p = models["profiles"][profile_name]
    body = {"model": p["model"], "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}], "response_format": {"type": "json_object"}}
    if effort:
        body["reasoning_effort"] = effort
    if max_tokens or p.get("max_tokens"):
        body["max_tokens"] = max_tokens or p["max_tokens"]
    req = urllib.request.Request(p["base_url"].rstrip("/") + "/chat/completions", data=json.dumps(body).encode(), headers={"Content-Type": "application/json", "Authorization": "Bearer " + e[p["key_env"]]})
    last = None
    for attempt in range(tries):
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=600) as r:
                v = json.loads(r.read())
            text = v["choices"][0]["message"]["content"]
            text = text if isinstance(text, str) else "".join(x.get("text", "") for x in text)
            u = v.get("usage", {})
            if LOG_PATH:
                with LOG_LOCK, open(LOG_PATH, "a") as f:
                    f.write(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "purpose": purpose, "profile": profile_name, "model": p["model"], "effort": effort, "prompt": u.get("prompt_tokens", 0), "cached": (u.get("prompt_tokens_details") or {}).get("cached_tokens", 0), "completion": u.get("completion_tokens", 0), "seconds": round(time.time() - t0, 1)}) + "\n")
            a, b = text.find("{"), text.rfind("}")
            return json.loads(text[a : b + 1])
        except Exception as ex:  # noqa: BLE001 - retried, then reported
            last = ex
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"model call failed ({purpose}): {last}")


def rules_catalog():
    """Item and technique names the rules define."""
    src = (ROOT / "living/rules/src/catalog.rs").read_text()
    items = set(re.findall(r'ItemSpec \{ name: "([a-z_]+)"', src))
    techniques = set(re.findall(r'TechniqueSpec \{ name: "([a-z_]+)"', src))
    return items, techniques


CAST_SYSTEM = """You plan the households of one settlement of a persistent simulated world, at the moment the world begins. You write who lives there and what is going on between them now. You never write what happens next.

Rules:
- Fit the world bible: this settlement's culture, names, faith, trades and the world tensions as this settlement sees them.
- Every anchor person listed for this settlement appears exactly as given (same name, age, sex, occupation, household key, role, parents, ties); add their family and neighbours around them. Anchors of other settlements may be named in ties, spelled exactly.
- Invent everyone else in this settlement's naming style, with real variety: no first name more than twice in the settlement, none of the first names listed as already used, and family names of their own (kin share one; unrelated households differ). Never reuse a full name from the roster. The bible's names are examples of the style, not a list to draw from.
- Households are families or shared houses: 1-6 people, adults with children, elders living with their grown children, a few people living alone, an apprentice lodging with a master. Children's occupation is "child" (ages 1-13). Ages are whole years.
- Occupation is one of the allowed occupations. Follow the occupation mix roughly; children are extra.
- knows: techniques from the allowed list that fit their trade and age (adults usually also know fire). Children know little.
- parents: up to two names of people in the cast (this settlement or anchors elsewhere).
- ties: short lines naming the people they are tied to (kin, love, work, debt, grudge, friendship), 2-6 for adults. Prefix a tie that the other side or others do not know with "SECRET: ".
- situations: 4-8 situations among this settlement's people (and anchors elsewhere where the bible says so) that give it motion: a debt, a courtship, a feud, a missing person, a failing harvest, an apprenticeship, a rivalry, an illness, an inheritance, a secret, a quarrel with another settlement. Each names 2-5 people, says plainly what the situation is now, and for each person what they know and feel about it. A secret situation lists who knows it in "people"; nobody else knows. A situation is a starting state, not a plot: no outcome, no plan of events.

Reply with ONE JSON object:
{"households": [{"key": "short-lowercase-key", "members": [{"name": "...", "age": 30, "sex": "f|m", "occupation": "...", "role": "one line: who they are here", "knows": ["..."], "parents": ["..."], "ties": ["..."]}]}],
 "situations": [{"id": "short-key", "kind": "debt|courtship|feud|...", "summary": "what it is now, in one or two sentences", "secret": false, "people": ["..."], "sides": {"<name>": "what this person knows and feels about it"}}]}"""


ISLAND_SYSTEM = SYSTEM.replace("Dead people (like Tomas) may appear in memories and stances but never in relations.", "The dead may appear in memories and stances but never in relations.").replace(
    "(older people remember the Hunger Winter or the Oath; others last winter, trade days, Tomas's death, small family moments)", "(the history in the bible as they lived it: the Lean Year, the Surge, the broken match, the cairn cutting; and small family and work moments)"
) + """
- Situations below are facts of the world as each person in them sees them: write the person's sheet so it agrees with their side (relations, memories, stances, goals). A person who is not in a situation's people list does not know about it.
- Write in English. Keep marks, goods and places to what the bible names."""


def roster_lines(world, casts):
    """Everyone drafted so far and every anchor: the public roster other drafts must agree with."""
    lines, seen = [], set()
    for s in world["settlements"]:
        c = casts.get(s["name"])
        people = [(h["key"], m) for h in c["households"] for m in h["members"]] if c else [(a["household"], a) for a in s["anchors"]]
        for key, m in people:
            if m["name"] in seen:
                continue
            seen.add(m["name"])
            ties = [t for t in m.get("ties", []) if not t.startswith("SECRET")]
            lines.append(f"- {m['name']} ({m['age']:g}, {m['sex']}, {s['name']}, household {key}): {m.get('role', m.get('occupation', ''))}. Ties: {'; '.join(ties)}")
    return "\n".join(lines)


def draft_cast(world, bible, s, casts, profile, effort, taken):
    anchors = json.dumps(s["anchors"], ensure_ascii=False, indent=1)
    others = "\n".join(f"- {o['name']}: {o['brief']}" for o in world["settlements"] if o is not s)
    routes = "\n".join(f"- {r['about']}: {r['occupation']} from {r['from']} to {r['to']}, carrying {r['out']} out and {r['back']} back" for r in world.get("routes", []))
    user = f"""# World bible
{bible}

# The other settlements
{others}

# Roads and carriers
{routes}

# People already known across the island (anchors and drafted settlements)
{roster_lines(world, casts)}

# Plan this settlement: {s['name']}
{s['brief']}

About {s['people']} people in about {s['households']} households (children included).
Occupation mix (adults, roughly): {json.dumps(s['mix'])}
Allowed occupations: {', '.join(world['occupations'])}, child
Allowed techniques: {', '.join(sorted(TECHNIQUES_ALLOWED))}
Anchor people (include exactly, with their households filled out):
{anchors}

First names already used on the island (avoid them): {', '.join(sorted({n.split()[0] for n in taken}))}

Plan {s['households']} households and about {s['people']} people."""
    v = logged_call(profile, CAST_SYSTEM, user, effort, f"cast:{s['name']}")
    # Too few people: ask for more households beside the ones planned.
    for _ in range(2):
        have = sum(len(h.get("members", [])) for h in v.get("households", []))
        if have >= s["people"] * 0.85:
            break
        more = f"""{user}

# Already planned for {s['name']}
{json.dumps(v, ensure_ascii=False)}

That is {have} people. Add about {s['people'] - have} more people in new households (new keys, new names, same rules) to reach the target, and any situations they are in. Reply with only the new households and new situations, in the same JSON shape."""
        w = logged_call(profile, CAST_SYSTEM, more, effort, f"cast-more:{s['name']}")
        v.setdefault("households", []).extend(w.get("households", []))
        v.setdefault("situations", []).extend(w.get("situations", []))
    return v


TECHNIQUES_ALLOWED = set()


def check_cast(world, s, cast, taken, notes):
    """Make a drafted settlement fit: anchors as given, unique names, known occupations and
    techniques, parents who exist, sane ages. Returns the cleaned cast."""
    allowed_occ = set(world["occupations"]) | {"child"}
    hh = {h["key"]: h for h in cast.get("households", []) if h.get("key") and h.get("members")}
    # Anchors exactly as world.json gives them, in their households.
    for a in s["anchors"]:
        for h in hh.values():
            h["members"] = [m for m in h["members"] if m.get("name") != a["name"]]
        h = hh.setdefault(a["household"], {"key": a["household"], "members": []})
        m = {"name": a["name"], "age": a["age"], "sex": a["sex"], "occupation": a["occupation"], "role": a["role"], "knows": [], "parents": a.get("parents", []), "ties": a.get("ties", [])}
        h["members"].insert(0, m)
    names = set()
    for h in hh.values():
        keep = []
        for m in h["members"]:
            n = str(m.get("name", "")).strip()
            if not n or n in names or (n in taken and n not in {a["name"] for a in s["anchors"]}):
                notes.append(f"{s['name']}: duplicate or empty name {n!r} dropped")
                continue
            names.add(n)
            m["name"] = n
            try:
                m["age"] = max(0, min(90, int(round(float(m.get("age", 30))))))
            except (TypeError, ValueError):
                m["age"] = 30
            m["sex"] = "f" if str(m.get("sex", "f")).lower().startswith("f") else "m"
            occ = str(m.get("occupation", "")).strip().lower()
            if m["age"] < 14:
                occ = "child"
            if occ not in allowed_occ:
                notes.append(f"{s['name']}: {n}'s occupation {occ!r} is not allowed; farmer")
                occ = "farmer"
            m["occupation"] = occ
            m["knows"] = [k for k in m.get("knows", []) if k in TECHNIQUES_ALLOWED]
            if occ != "child" and "fire" not in m["knows"]:
                m["knows"].append("fire")
            m["ties"] = [str(t) for t in m.get("ties", []) if str(t).strip()][:8]
            m["role"] = str(m.get("role", occ))
            keep.append(m)
        h["members"] = keep
    out = [h for h in hh.values() if h["members"]]
    sits = []
    for x in cast.get("situations", []):
        people = [p for p in x.get("people", []) if isinstance(p, str)]
        if len(people) < 2 or not x.get("summary"):
            continue
        sits.append({"id": slug(str(x.get("id", "") or x["summary"][:24])), "kind": str(x.get("kind", "")), "summary": str(x["summary"]), "secret": bool(x.get("secret")), "people": people, "sides": {k: str(v) for k, v in (x.get("sides") or {}).items() if k in people}})
    return {"households": out, "situations": sits}


def carry_graph(out, back, n, reach=90):
    """The starting routine of someone who carries goods between two markets along a known way:
    `work 1` .. `work n-1` are stages along the roads to `work`, the far market; `square` is home.
    Graphs are weighed again while a walk goes on, so each rule must stay true for a whole leg:
    within `reach` metres of a stage, walk to it, the furthest such stage first (outbound) or the
    nearest to home first (inbound). With stages closer together than `reach`, but two stages
    farther apart than it, a carrier keeps to the road from stage to stage instead of cutting
    across. A graph holds at most 80 nodes (living_rules::graph), about 14 stages each way."""
    near = lambda p, r: {"near": {"target": {"place": p}, "within": r}}  # noqa: E731
    has = lambda it, k: {"has": {"item": it, "at_least": k}}  # noqa: E731
    goto = lambda p: {"do": "goto", "target": {"place": p}}  # noqa: E731
    stage = lambda k: "work" if k >= n else f"work {k}"  # noqa: E731
    outbound = [{"if": near("work", 6), "then": {"do": "store", "target": {"nearest": "storage"}, "item": out, "qty": 3}}]
    outbound += [{"if": near(stage(k), reach), "then": goto(stage(k))} for k in range(n, 0, -1)]
    outbound.append(goto(stage(1)))
    inbound = [{"if": near("square", 6), "then": {"do": "store", "target": {"nearest": "storage"}, "item": back, "qty": 3}}]
    inbound.append({"if": near("square", reach), "then": goto("square")})
    inbound += [{"if": near(stage(k), reach), "then": goto(stage(k))} for k in range(1, n)]
    inbound.append(goto(stage(n - 1)))
    # A composite holds at most 12 children (living_rules::graph): long ways nest their stages,
    # and a nested `first` with no rule that applies falls through to the next.
    def fit(rules):
        if len(rules) <= 12:
            return rules
        head, stages, tail = rules[:1], rules[1:-1], rules[-1:]
        return head + [{"first": stages[i : i + 10]} for i in range(0, len(stages), 10)] + tail

    outbound, inbound = fit(outbound), fit(inbound)
    return {"first": [
        {"if": has(out, 3), "then": {"first": outbound}},
        {"if": {"all": [near("work", 8), {"not": has(back, 3)}]}, "then": {"do": "take", "target": {"nearest": "storage"}, "item": back, "qty": 3}},
        {"if": has(back, 3), "then": {"first": inbound}},
        {"if": near("square", 8), "then": {"do": "take", "target": {"nearest": "storage"}, "item": out, "qty": 3}},
        goto("square"),
    ]}


def situations_text(sits, names):
    lines = []
    for x in sits:
        mine = [n for n in x["people"] if n in names]
        if not mine:
            continue
        lines.append(f"- [{x['kind']}{', secret' if x['secret'] else ''}] {x['summary']} People in it: {', '.join(x['people'])}.")
        for n in mine:
            if x["sides"].get(n):
                lines.append(f"  {n}'s side: {x['sides'][n]}")
    return "\n".join(lines)


NAMES_SYSTEM = """You decide, for people of a simulated world at the moment it begins, which other people they know by name: would they recognise the person on meeting them and know what to call them? Relatives, neighbours, trade partners, creditors and debtors, people they have dealt with, quarrelled with or been introduced to: yes. Someone they know only by reputation or from others' talk and have never met, someone they have only glimpsed, a stranger: no. Someone they know by sight and whose name everyone uses (a well-known leader, an outlaw they have faced): yes.

Reply with ONE JSON object: {"pairs": [{"person": "...", "other": "...", "knows_name": true}]} with one entry for each pair asked."""


def names_settlement(s, cast, sheets, home, profile, effort):
    """Which of a settlement's people know by name the people outside their community they have
    feelings about. Since names spread only as the world projects them (a feeling is not an
    introduction), each authored relation becomes an introduction unless this says no."""
    lines = []
    for h in cast["households"]:
        for m in h["members"]:
            sh = sheets.get(m["name"])
            for r in (sh or {}).get("relations", []):
                if home.get(r["name"]) not in (None, s["name"]):
                    lines.append(f"- {m['name']} ({m['role']}) -> {r['name']} of {home[r['name']]}: {r['label']}. \"{r['note']}\"")
    if not lines:
        return {}
    v = logged_call(profile, NAMES_SYSTEM, f"# People of {s['name']} and the people elsewhere they feel something about\n" + "\n".join(lines), effort, f"names:{s['name']}")
    return {f"{x['person']}|{x['other']}": bool(x.get("knows_name", True)) for x in v.get("pairs", []) if isinstance(x, dict) and x.get("person") and x.get("other")}


REVIEW_SYSTEM = """You check the character sheets of a simulated world for contradictions before the world starts. Situations are the agreed facts. Compare each situation with the sheets of the people in it, and the people's sheets with each other.

A contradiction is: two sheets disagree on a fact (who owes whom, how much, who is courting whom, who is whose parent or spouse, who did what in a remembered event); a sheet contradicts a situation it is in; a person knows a secret they are not in; a relation's feeling flatly contradicts the situation (lovers who are strangers; a creditor who does not know the debt). Different opinions about the same fact are NOT contradictions. Missing detail is not a contradiction.

Reply with ONE JSON object: {"issues": [{"person": "<name whose sheet should change>", "with": "<other name or situation id>", "problem": "one line", "fix": "one line: what their sheet should say"}]} (empty list if none)."""


def review_settlement(world, s, cast, sheets, profile, effort):
    names = {m["name"] for h in cast["households"] for m in h["members"]}
    blocks = []
    for x in cast["situations"]:
        blocks.append(f"## Situation {x['id']} [{x['kind']}{', secret' if x['secret'] else ''}]: {x['summary']}\nPeople: {', '.join(x['people'])}")
        for n in x["people"]:
            sh = sheets.get(n)
            if not sh:
                continue
            rel = [r for r in sh["relations"] if r["name"] in x["people"]]
            mem = [m["gist"] for m in sh["memories"] if set(m.get("about", [])) & set(x["people"])]
            blocks.append(f"### {n} (side: {x['sides'].get(n, '-')})\nnarrative: {sh['narrative']}\nrelations: {json.dumps(rel, ensure_ascii=False)}\nmemories: {json.dumps(mem, ensure_ascii=False)}\nstances: {json.dumps([st['key'] + ': ' + st['why'] for st in sh['stances']], ensure_ascii=False)}\ngoals: {json.dumps(sh['goals'], ensure_ascii=False)}")
    # Kin: each person's family relations, both ways.
    kin = []
    for h in cast["households"]:
        for m in h["members"]:
            sh = sheets.get(m["name"])
            if sh:
                kin.append(f"- {m['name']} ({m['age']}), parents {m.get('parents', [])}: " + "; ".join(f"{r['label']} {r['name']}" for r in sh["relations"] if r["name"] in names and FAMILY.search(r["label"])))
    user = f"# Settlement {s['name']}\n\n" + "\n\n".join(blocks) + "\n\n## Family as each sheet states it\n" + "\n".join(kin)
    try:
        return logged_call(profile, REVIEW_SYSTEM, user, effort, f"review:{s['name']}", tries=2).get("issues", [])
    except RuntimeError:
        # A reviewer that runs out of room (GLM at high effort can think past its token cap)
        # hands over to DeepSeek with thinking.
        return logged_call("deepseek-flash", REVIEW_SYSTEM, user, "high", f"review-fallback:{s['name']}", tries=2).get("issues", [])


def entries_walled(seed, s):
    t = next((t for t in seed.get("towns", []) + seed.get("villages", []) if t["name"] == s["name"]), None)
    return t.get("walled", True) if t else False


def lives(a, wd):
    global LOG_PATH, TECHNIQUES_ALLOWED
    LOG_PATH = wd / "authoring-log.jsonl"
    world = json.loads((wd / "world.json").read_text())
    ways = json.loads((wd / "ways.json").read_text()) if (wd / "ways.json").exists() else {}
    bible = (wd / "bible.md").read_text()
    items, TECHNIQUES_ALLOWED = rules_catalog()
    (wd / "cast").mkdir(exist_ok=True)
    (wd / "sheets").mkdir(exist_ok=True)
    only = {x.strip() for x in a.only.split(",")} if a.only else None
    settlements = [s for s in world["settlements"] if only is None or s["name"] in only]
    notes = []

    # 1. Cast, one settlement at a time in world.json order, so later ones see earlier names.
    casts = {}
    for s in world["settlements"]:
        f = wd / "cast" / f"{slug(s['name'])}.json"
        if f.exists():
            casts[s["name"]] = json.loads(f.read_text())
    taken = {m["name"] for c in casts.values() for h in c["households"] for m in h["members"]} | {x["name"] for s in world["settlements"] for x in s["anchors"]}
    for s in settlements:
        f = wd / "cast" / f"{slug(s['name'])}.json"
        if f.exists() or a.compile_only:
            continue
        print(f"cast: {s['name']} with {a.profile}", flush=True)
        raw = draft_cast(world, bible, s, casts, a.profile, a.effort, taken)
        c = check_cast(world, s, raw, taken, notes)
        firsts = {}
        for h in c["households"]:
            for m in h["members"]:
                firsts[m["name"].split()[0]] = firsts.get(m["name"].split()[0], 0) + 1
        crowded = {k: v for k, v in firsts.items() if v > 2}
        if crowded:
            notes.append(f"{s['name']}: first names used more than twice: {crowded}")
        f.write_text(json.dumps(c, indent=1, ensure_ascii=False) + "\n")
        casts[s["name"]] = c
        taken |= {m["name"] for h in c["households"] for m in h["members"]}
        print(f"  {sum(len(h['members']) for h in c['households'])} people in {len(c['households'])} households, {len(c['situations'])} situations", flush=True)
    ready = [s for s in settlements if s["name"] in casts]
    # The cast in the shape the sheet drafting already uses.
    cast_all = {"settlements": [{"name": s["name"], "households": casts[s["name"]]["households"]} for s in world["settlements"] if s["name"] in casts]}
    # Anchors of settlements not drafted yet count as people: their names stay in sheets, and
    # the world drops what names no one when it is built.
    names = {m["name"] for _, _, m in people_of(cast_all)} | {x["name"] for s in world["settlements"] for x in s["anchors"]}
    sits_all = [x for c in casts.values() for x in c["situations"]]

    # 2. Sheets per household, with the situations its members are in.
    def draft(s, h, extra=""):
        members = "\n".join(f"- {m['name']} ({m['age']:g}, {m['sex']}), {m['role']}. Occupation: {m['occupation']}. Knows: {', '.join(m['knows']) or 'nothing yet'}. Ties: {'; '.join(m.get('ties', []))}" for m in h["members"])
        mine = {m["name"] for m in h["members"]}
        user = f"""# World bible
{bible}

# The whole cast (public knowledge)
{roster_lines(world, casts)}

# Situations these people are part of
{situations_text(sits_all, mine) or '(none)'}

# Write sheets for this household of {s['name']} ({h['key']})
{members}
{extra}
Write one sheet for each of: {', '.join(m['name'] for m in h['members'])}."""
        v = logged_call(a.profile, ISLAND_SYSTEM, user, a.effort, f"sheets:{s['name']}/{h['key']}")
        return v.get("sheets", v)

    def sheet_file(s, h):
        return wd / "sheets" / f"{slug(s['name'])}--{h['key']}.json"

    if not a.compile_only:
        todo = [(s, h) for s in ready for h in casts[s["name"]]["households"] if not sheet_file(s, h).exists()]
        print(f"drafting {len(todo)} households with {a.profile}", flush=True)
        with concurrent.futures.ThreadPoolExecutor(a.jobs) as ex:
            futs = {ex.submit(draft, s, h): (s, h) for s, h in todo}
            for fu in concurrent.futures.as_completed(futs):
                s, h = futs[fu]
                try:
                    got = fu.result()
                except Exception as e:  # noqa: BLE001
                    print(f"  {s['name']}/{h['key']}: {e}", flush=True)
                    continue
                missing = [m["name"] for m in h["members"] if m["name"] not in got]
                if missing:
                    print(f"  {s['name']}/{h['key']}: no sheet for {missing}; rerun to redraft", flush=True)
                    continue
                sheet_file(s, h).write_text(json.dumps({m["name"]: got[m["name"]] for m in h["members"]}, indent=2, ensure_ascii=False) + "\n")

    def load_sheets():
        out = {}
        for s in world["settlements"]:
            for h in casts.get(s["name"], {}).get("households", []):
                f = sheet_file(s, h)
                if f.exists():
                    raw = json.loads(f.read_text())
                    for m in h["members"]:
                        out[m["name"]] = check_sheet(m["name"], raw.get(m["name"], {}), names, notes)
        return out

    sheets = load_sheets()
    person = {m["name"]: (s, h, m) for s, h, m in people_of(cast_all)}
    by_name = {s["name"]: s for s in world["settlements"]}

    # 3. Ties felt both ways: family, household, named ties and everyone in a shared situation.
    def one_sided():
        missing = {}
        shared = {}
        for x in sits_all:
            for p in x["people"]:
                shared.setdefault(p, set()).update(q for q in x["people"] if q != p)
        for n, sh in sheets.items():
            for r in sh["relations"]:
                o = r["name"]
                if o not in sheets or any(x["name"] == n for x in sheets[o]["relations"]):
                    continue
                tie_text = " ".join(person[o][2].get("ties", []))
                if person[o][1]["key"] == person[n][1]["key"] and person[o][0]["name"] == person[n][0]["name"] or FAMILY.search(r["label"]) or n in tie_text or n in shared.get(o, ()):
                    missing.setdefault(o, set()).add(n)
            for o in shared.get(n, ()):
                if o in sheets and not any(x["name"] == o for x in sh["relations"]):
                    missing.setdefault(n, set()).add(o)
        return missing

    if not a.compile_only:
        missing = one_sided()
        print(f"filling {sum(len(v) for v in missing.values())} one-sided ties", flush=True)

        def fill(o, others):
            s, h, m = person[o]
            user = f"# World bible\n{bible}\n\n# The whole cast (public knowledge)\n{roster_lines(world, casts)}\n\n# Situations {o} is part of\n{situations_text(sits_all, {o}) or '(none)'}\n\n# Person\n{o} ({m['age']:g}), {m['role']}. Ties: {'; '.join(m.get('ties', []))}\nTheir current relations: {json.dumps(sheets[o]['relations'], ensure_ascii=False)}\n\nWrite how {o} feels about: {', '.join(sorted(others))}. Reply with ONE JSON object: {{\"relations\": [{{\"name\": \"...\", \"trust\": 0, \"affinity\": 0, \"label\": \"...\", \"note\": \"...\"}}]}}"
            return o, logged_call(a.profile, ISLAND_SYSTEM, user, a.effort, "fill")

        with concurrent.futures.ThreadPoolExecutor(a.jobs) as ex:
            for fu in concurrent.futures.as_completed([ex.submit(fill, o, v) for o, v in missing.items() if o in person and person[o][0]["name"] in {s["name"] for s in ready}]):
                try:
                    o, v = fu.result()
                except Exception as e:  # noqa: BLE001
                    notes.append(f"fill failed: {e}")
                    continue
                s, h, m = person[o]
                f = sheet_file(by_name[s["name"]], h)
                raw = json.loads(f.read_text())
                have = {r.get("name") for r in raw[o].get("relations", [])}
                raw[o].setdefault("relations", []).extend([r for r in v.get("relations", []) if r.get("name") in missing[o] and r.get("name") not in have])
                f.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n")
        sheets = load_sheets()

        # 4. Review, and one redraft of flagged households with the notes.
        if a.review:
            reviews = {}
            with concurrent.futures.ThreadPoolExecutor(a.jobs) as ex:
                futs = {ex.submit(review_settlement, world, s, casts[s["name"]], sheets, a.review, a.review_effort): s for s in ready}
                for fu in concurrent.futures.as_completed(futs):
                    s = futs[fu]
                    try:
                        issues = fu.result()
                    except RuntimeError as e:
                        notes.append(str(e))
                        continue
                    reviews[s["name"]] = issues
                    print(f"review {s['name']}: {len(issues)} issues", flush=True)
            prev = json.loads((wd / "review.json").read_text()) if (wd / "review.json").exists() else {}
            prev.update(reviews)
            (wd / "review.json").write_text(json.dumps(prev, indent=1, ensure_ascii=False) + "\n")
            if a.redraft:
                flagged = {}
                for issues in reviews.values():
                    for i in issues:
                        if i.get("person") in person:
                            flagged.setdefault(person[i["person"]][1]["key"] + "|" + person[i["person"]][0]["name"], []).append(i)
                for key, issues in flagged.items():
                    hk, sn = key.split("|", 1)
                    s = by_name[sn]
                    h = next(h for h in casts[sn]["households"] if h["key"] == hk)
                    extra = "\n# A reviewer found these problems in an earlier draft; fix them\n" + "\n".join(f"- {i['person']}: {i['problem']} -> {i.get('fix', '')}" for i in issues)
                    try:
                        got = draft(s, h, extra)
                    except RuntimeError as e:
                        notes.append(str(e))
                        continue
                    if all(m["name"] in got for m in h["members"]):
                        old = json.loads(sheet_file(s, h).read_text())
                        for m in h["members"]:
                            # Ties filled in step 3 stay unless the redraft names that person.
                            mine = {r.get("name") for r in got[m["name"]].get("relations", [])}
                            got[m["name"]].setdefault("relations", []).extend(r for r in old.get(m["name"], {}).get("relations", []) if r.get("name") not in mine)
                        sheet_file(s, h).write_text(json.dumps({m["name"]: got[m["name"]] for m in h["members"]}, indent=2, ensure_ascii=False) + "\n")
                print(f"redrafted {len(flagged)} households", flush=True)
                sheets = load_sheets()

    # 4b. Who knows whose name, for relations across communities (cached per settlement).
    home = {m["name"]: s["name"] for s in world["settlements"] if s["name"] in casts for h in casts[s["name"]]["households"] for m in h["members"]}
    (wd / "names").mkdir(exist_ok=True)
    known_names = {}
    for s in world["settlements"]:
        f = wd / "names" / f"{slug(s['name'])}.json"
        if not f.exists() and not a.compile_only and s in ready:
            try:
                f.write_text(json.dumps(names_settlement(s, casts[s["name"]], sheets, home, a.profile, a.effort), indent=1, ensure_ascii=False) + "\n")
            except RuntimeError as e:
                notes.append(str(e))
        if f.exists():
            known_names.update(json.loads(f.read_text()))

    # 5. Checks that need no model, then the compile.
    occupations_with_ways = set(json.loads((ROOT / "living/seeds/repertoire.json").read_text())["occupations"]) | set(ways.get("occupations", {})) | {r["occupation"] for r in world.get("routes", [])}
    seed_path = ROOT / "living/seeds" / f"{world['into']}.json"
    seed = json.loads(seed_path.read_text())
    occupations_with_ways |= set(seed.get("ways", {}).get("occupations", {}))
    problems = []
    for n, (s, h, m) in person.items():
        if m["occupation"] not in occupations_with_ways:
            problems.append(f"{n}: occupation {m['occupation']} has no starting ways")
        # A parent who is not on the island (the dead, or someone a draft only named) stays in
        # the person's sheet as memory; a parent too young to be one is not linked. Both noted.
        keep = []
        for p in m.get("parents", []):
            if p not in person:
                notes.append(f"{n}: parent {p} is not on the island; kept in their sheet only")
            elif person[p][2]["age"] < m["age"] + 14:
                notes.append(f"{n} ({m['age']}): parent {p} is only {person[p][2]['age']}; not linked")
            else:
                keep.append(p)
        m["parents"] = keep
        if n not in sheets:
            problems.append(f"{n}: no sheet")
    for w, kit in ways.get("kit", {}).items():
        problems += [f"kit {w}: {i} is not an item" for i in kit if i not in items]
    for s in world["settlements"]:
        problems += [f"{s['name']}: store {i} is not an item" for i in s["stores"] if i not in items]
        # A storage holds `storage_holds` things in all (living/scripts/skills.rhai); a walled
        # town's goods are split over two. Seeded stores leave room for what people bring.
        cap = world.get("store_holds", 120) * (2 if entries_walled(seed, s) else 1)
        if sum(s["stores"].values()) > cap * 0.8:
            problems.append(f"{s['name']}: stores hold {sum(s['stores'].values())} things, more than 80% of the {cap} its storages take")
    for r in world.get("routes", []):
        problems += [f"route {r['about']}: {i} is not an item" for i in (r["out"], r["back"]) if i not in items]
    one = sum(1 for n, sh in sheets.items() for r in sh["relations"] if r["name"] in sheets and not any(x["name"] == n for x in sheets[r["name"]]["relations"]))
    unshared = sum(len(v) for v in one_sided().values())
    for p in problems[:40]:
        print("  problem:", p)

    # Compile into the seed: residents, stores and ledger per settlement; ways; town life.
    entries = {t["name"]: t for t in seed.get("towns", []) + seed.get("villages", [])}
    route_of = {r["occupation"]: r for r in world.get("routes", [])}
    outlaws = world.get("outlaws", {})
    for s in world["settlements"]:
        if s["name"] not in casts:
            continue
        t = entries.get(s["name"])
        if t is None:
            t = {"name": s["name"], "site": s.get("site", "village"), "walled": False, "character": s["brief"].split(". ")[0].rstrip(".")}
            if s.get("near"):
                t["near"] = s["near"]
            if s.get("region"):
                t["region"] = s["region"]
            seed.setdefault("villages", []).append(t)
            entries[s["name"]] = t
        t["occupations"] = {}
        t["stores"] = s["stores"]
        t["ledger"] = s["ledger"]
        residents = []
        for h in casts[s["name"]]["households"]:
            for m in h["members"]:
                if m["name"] not in sheets:
                    continue
                sheet = json.loads(json.dumps(sheets[m["name"]]))
                for rel in sheet["relations"]:
                    # A relation is an introduction unless the names pass says this person would
                    # not know the other by name (docs/SEEDED_LIVES.md).
                    if known_names.get(f"{m['name']}|{rel['name']}") is False:
                        rel["knows_name"] = False
                r = {"name": m["name"], "age": m["age"], "household": h["key"], "occupation": m["occupation"], "knows": m["knows"], "parents": m.get("parents", []), "sheet": sheet}
                inv = dict(ways.get("kit", {}).get(m["occupation"], {"berries": 4}))
                if m["occupation"] in route_of:
                    ro = route_of[m["occupation"]]
                    inv[ro["out"]] = inv.get(ro["out"], 0) + 3
                    r["places"] = [{"name": "work", "in": ro["to"], "kinds": ["plaza"], "stages": ro.get("stages", 6)}]
                elif m["occupation"] == outlaws.get("occupation"):
                    r["places"] = [{"name": "work", "between": outlaws["road"]}]
                r["inventory"] = inv
                residents.append(r)
        t["residents"] = residents
    w = seed.setdefault("ways", {})
    w.setdefault("common", {}).update(ways.get("common", {}))
    occ = w.setdefault("occupations", {})
    occ.update(ways.get("occupations", {}))
    for r in world.get("routes", []):
        occ[r["occupation"]] = {"routine": f"carry {r['out'].replace('_', ' ')} on {r['about']}", "graph": carry_graph(r["out"], r["back"], r.get("stages", 6), r.get("reach_m", 90))}
    tl = seed.setdefault("town_life", {}).setdefault("work", {})
    tl.update(ways.get("work", {}))
    for r in world.get("routes", []):
        tl[r["occupation"]] = ["plaza"]
    # Records the world starts with (a community's regard for another; docs/WORLD_RULES.md).
    if world.get("records"):
        seed["records"] = world["records"]
    seed_path.write_text(json.dumps(seed, indent=2, ensure_ascii=False) + "\n")
    n_rel = sum(len(s["relations"]) for s in sheets.values())
    print(f"wrote {seed_path.relative_to(ROOT)}: {len([s for s in world['settlements'] if s['name'] in casts])} settlements, {len(sheets)} residents; {n_rel} relations ({one} one-sided, {unshared} family/named/situation ties still one-sided), {sum(len(s['memories']) for s in sheets.values())} memories, {sum(len(s['stances']) for s in sheets.values())} stances, {sum(1 for s in sheets.values() if s.get('secret'))} secrets, {len(sits_all)} situations; {len(problems)} problems")
    for n in notes[:30]:
        print("  note:", n)
    if LOG_PATH.exists():
        rows = [json.loads(x) for x in LOG_PATH.read_text().splitlines() if x.strip()]
        print(f"model calls so far: {len(rows)}, prompt {sum(r['prompt'] for r in rows):,} (cached {sum(r['cached'] for r in rows):,}), completion {sum(r['completion'] for r in rows):,} tokens")
    return 1 if problems and a.strict else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("world")
    ap.add_argument("--profile", default="glm-flash")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--compile-only", action="store_true")
    # Seeded lives (a world directory with world.json; docs/SEEDED_LIVES.md).
    ap.add_argument("--effort", default=None, help="reasoning effort to send (none: not sent)")
    ap.add_argument("--only", default="", help="comma-separated settlements to draft (cast, sheets, review)")
    ap.add_argument("--review", default="", help="profile for the review pass (none: no review)")
    ap.add_argument("--review-effort", default=None)
    ap.add_argument("--redraft", action="store_true", help="redraft households the review flags, once")
    ap.add_argument("--strict", action="store_true", help="exit 1 when the checks find problems")
    a = ap.parse_args()
    wd = ROOT / "living/seeds/worlds" / a.world
    if (wd / "world.json").exists():
        sys.exit(lives(a, wd))
    cast = json.loads((wd / "cast.json").read_text())
    bible = (wd / "bible.md").read_text()
    names = {m["name"] for _, _, m in people_of(cast)}
    sheets_dir = wd / "sheets"
    sheets_dir.mkdir(exist_ok=True)

    if not a.compile_only:
        todo = [(s, h) for s in cast["settlements"] for h in s["households"] if not (sheets_dir / f"{h['key']}.json").exists()]
        print(f"drafting {len(todo)} households with {a.profile}", flush=True)
        with concurrent.futures.ThreadPoolExecutor(a.jobs) as ex:
            futs = {ex.submit(draft_household, wd, cast, bible, s, h, a.profile): h for s, h in todo}
            for f in concurrent.futures.as_completed(futs):
                h = futs[f]
                try:
                    got = f.result()
                except Exception as e:  # noqa: BLE001
                    print(f"  {h['key']}: {e}", flush=True)
                    continue
                missing = [m["name"] for m in h["members"] if m["name"] not in got]
                if missing:
                    print(f"  {h['key']}: no sheet for {missing}; rerun to redraft", flush=True)
                    continue
                (sheets_dir / f"{h['key']}.json").write_text(json.dumps({m["name"]: got[m["name"]] for m in h["members"]}, indent=2, ensure_ascii=False) + "\n")
                print(f"  {h['key']}: {len(h['members'])} sheets", flush=True)

    sheets, notes = {}, []
    for s, h, m in people_of(cast):
        f = sheets_dir / f"{h['key']}.json"
        if not f.exists():
            sys.exit(f"missing sheets for household {h['key']}; draft first")
        raw = json.loads(f.read_text())
        sheets[m["name"]] = check_sheet(m["name"], raw.get(m["name"], {}), names, notes)

    # Family, household and named ties must be felt both ways; draft the missing sides.
    household_of = {m["name"]: h["key"] for _, h, m in people_of(cast)}
    person = {m["name"]: (s, h, m) for s, h, m in people_of(cast)}
    missing = {}
    for n, sh in sheets.items():
        for r in sh["relations"]:
            o = r["name"]
            if any(x["name"] == n for x in sheets[o]["relations"]):
                continue
            tie_text = " ".join(person[o][2].get("ties", []))
            if household_of[o] == household_of[n] or FAMILY.search(r["label"]) or n in tie_text:
                missing.setdefault(o, []).append(n)
    if missing and not a.compile_only:
        print(f"filling {sum(len(v) for v in missing.values())} one-sided family or named ties", flush=True)
        for o, others in missing.items():
            s, h, m = person[o]
            user = f"# World bible\n{bible}\n\n# The whole cast (public knowledge)\n{roster(cast)}\n\n# Person\n{o} ({m['age']:g}), {m['role']}. Ties: {'; '.join(m.get('ties', []))}\nTheir current relations: {json.dumps(sheets[o]['relations'], ensure_ascii=False)}\n\nWrite how {o} feels about: {', '.join(others)}. Reply with ONE JSON object: {{\"relations\": [{{\"name\": \"...\", \"trust\": 0, \"affinity\": 0, \"label\": \"...\", \"note\": \"...\"}}]}}"
            try:
                v = model_call(a.profile, SYSTEM, user, effort="low")
            except RuntimeError as e:
                notes.append(f"{o}: fill failed: {e}")
                continue
            f = sheets_dir / f"{h['key']}.json"
            raw = json.loads(f.read_text())
            raw[o].setdefault("relations", []).extend([r for r in v.get("relations", []) if r.get("name") in others])
            f.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n")
            sheets[o] = check_sheet(o, raw[o], names, notes)

    seed = json.loads((wd / "seed.json").read_text())
    towns, villages = [], []
    for s in cast["settlements"]:
        residents = []
        for h in s["households"]:
            for m in h["members"]:
                r = {"name": m["name"], "age": m["age"], "household": h["key"], "occupation": m["occupation"], "knows": m["knows"], "parents": m.get("parents", []), "sheet": sheets[m["name"]]}
                if m.get("inventory"):
                    r["inventory"] = m["inventory"]
                residents.append(r)
        t = {"name": s["name"], "character": s["character"], "walled": s["walled"], "occupations": {}, "stores": s["stores"], "resources": s.get("resources", {}), "ledger": s["ledger"], "buildings": s.get("buildings", []), "residents": residents}
        (villages if s["kind"] == "village" else towns).append(t)
    seed["towns"], seed["villages"] = towns, villages
    out = ROOT / "living/seeds" / f"{a.world}.json"
    out.write_text(json.dumps(seed, indent=2, ensure_ascii=False) + "\n")
    one_sided = sum(1 for n, sh in sheets.items() for r in sh["relations"] if not any(x["name"] == n for x in sheets[r["name"]]["relations"]))
    print(f"wrote {out.relative_to(ROOT)}: {len(towns)} towns, {len(villages)} villages, {len(sheets)} residents; {sum(len(s['relations']) for s in sheets.values())} relations ({one_sided} one-sided), {sum(len(s['memories']) for s in sheets.values())} memories, {sum(len(s['stances']) for s in sheets.values())} stances, {sum(1 for s in sheets.values() if s.get('secret'))} secrets")
    for n in notes[:30]:
        print("  note:", n)


if __name__ == "__main__":
    main()
