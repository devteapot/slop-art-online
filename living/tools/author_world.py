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
- A life is more than its troubles: goals mix ambitions, care for particular people and things they want for themselves, not only the quarrels and debts of the situations. Pastimes: 2-3 things they enjoy doing for their own sake (a song, a game, carving, fishing at dusk, a walk to a place they love, visiting someone). Calling: one line on the work they love, or the work they long for instead of their own.
- Babies and small children: a short simple narrative (a baby's is sensation), a few relations to family, one or two memories at most, no stances; a small child's pastimes are play.

Reply with ONE JSON object: {"sheets": {"<name>": {"narrative": "first person, 2-5 sentences", "values": [...], "goals": [...], "pastimes": [...], "calling": "...", "mood": "...", "traits": {...}, "relations": [{"name": "...", "trust": 0, "affinity": 0, "label": "...", "note": "..."}], "memories": [{"gist": "...", "salience": 0.5, "about": ["..."]}], "stances": [{"key": "...", "value": 0.8, "why": "..."}], "secret": "... or empty"}}}"""


def draft_household(world_dir, cast, bible, s, h, profile, effort=None):
    if cast.get("prompt"):
        # A cast with anchors (wants, what is going on, rhythm, secrets, situations): Cullet's.
        # About 1,700 output tokens a sheet (the island's journal): a house of seven needs more
        # than a profile's usual 8,000.
        cap = min(24000, max(8000, 2500 * len(h["members"])))
        v = logged_call(profile, sheet_system(cast), household_prompt(world_dir, cast, bible, s, h), effort, f"sheets:{h['key']}", max_tokens=cap)
        return v.get("sheets", v)
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
    out["pastimes"] = [str(x)[:120] for x in sheet.get("pastimes", []) if str(x).strip()][:4]
    calling = str(sheet.get("calling", "") or "").strip()
    if calling:
        out["calling"] = calling[:200]
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
    `work 1` .. `work n-1` are stages along the roads to `work`, the far market's store; `store`
    (a `town_life` place) is the store at home. Both ends are stores, not squares: one takes from
    and stores into a storage beside one, found by sight (11 m by day), and a big square's spot
    can be farther than that from its stores (Highshelf's giants' plaza: 43 m).
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
    inbound = [{"if": near("store", 6), "then": {"do": "store", "target": {"nearest": "storage"}, "item": back, "qty": 3}}]
    inbound.append({"if": near("store", reach), "then": goto("store")})
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
        {"if": near("store", 8), "then": {"do": "take", "target": {"nearest": "storage"}, "item": out, "qty": 3}},
        goto("store"),
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
        # A storage holds its kind's `holds` things in all (120, living/scripts/skills.rhai); a walled
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
                    r["places"] = [{"name": "work", "in": ro["to"], "kinds": ["storage"], "stages": ro.get("stages", 6)}]
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


# ---- a hand-written cast with anchors and a plan (Cullet, docs/SMALL_CITY.md section 3) --------
#
# cast.json may carry, beyond the Aske Coast's shape: `plan` (the world's plan file, so each
# household's `lot` binds it to its house through `SeedTown.homes`), `counts` (what the cast must
# add up to), `prompt` (the world's words for the sheet prompt), per member `trade`, `wants`,
# `going_on` (the anchors a sheet must honour), `kin` (each relative and what they are to this
# person), `rhythm` (the starting day) and `secret`; top level `secrets` (who knows what),
# `situations` (with every side's view, as the island's planned casts have) and `tensions`.
# `--check` checks it without a model; `--dry-run` also builds every prompt the drafting would
# send, estimates the spend and previews the compiled residents, and never touches the network.

KIN = {
    # word: (relation, sex of the relative named, inverse relation)
    "mother": ("parent", "f", "child"), "father": ("parent", "m", "child"),
    "son": ("child", "m", "parent"), "daughter": ("child", "f", "parent"),
    "brother": ("sibling", "m", "sibling"), "sister": ("sibling", "f", "sibling"),
    "husband": ("spouse", "m", "spouse"), "wife": ("spouse", "f", "spouse"),
    "grandmother": ("grandparent", "f", "grandchild"), "grandfather": ("grandparent", "m", "grandchild"),
    "grandson": ("grandchild", "m", "grandparent"), "granddaughter": ("grandchild", "f", "grandparent"),
    "aunt": ("auncle", "f", "nibling"), "uncle": ("auncle", "m", "nibling"),
    "niece": ("nibling", "f", "auncle"), "nephew": ("nibling", "m", "auncle"),
    "great-aunt": ("grandauncle", "f", "grandnibling"), "great-uncle": ("grandauncle", "m", "grandnibling"),
    "great-niece": ("grandnibling", "f", "grandauncle"), "great-nephew": ("grandnibling", "m", "grandauncle"),
    "cousin": ("cousin", None, "cousin"),
    "mother-in-law": ("parent-in-law", "f", "child-in-law"), "father-in-law": ("parent-in-law", "m", "child-in-law"),
    "son-in-law": ("child-in-law", "m", "parent-in-law"), "daughter-in-law": ("child-in-law", "f", "parent-in-law"),
    "brother-in-law": ("sibling-in-law", "m", "sibling-in-law"), "sister-in-law": ("sibling-in-law", "f", "sibling-in-law"),
}

# EUR per million tokens (input, cached input, output), from docs/MODEL_COST.md (2026 price table).
PRICES_EUR = {"deepseek-v4-1-flash-1017": (0.255, 0.006, 1.02), "zai-glm-5-3-flash": (0.1275, 0.0255, 0.425)}
# From the island's authoring journal (docs/SEEDED_LIVES.md "Spend"): 482,134 sheet output
# tokens for 277 residents; 133 tie-filling calls for 277 residents, 20,367 output tokens.
OUT_PER_SHEET = 482134 / 277
FILLS_PER_PERSON = 133 / 277
OUT_PER_FILL = 20367 / 133


def rhai_names(src, fn):
    """The `name:` entries of a Rhai table function (`fn items() { [...] }`) in a script."""
    m = re.search(r"\nfn " + re.escape(fn) + r"\(\)\s*\{(.*?)\n\}", "\n" + src, re.S)
    return set(re.findall(r'name: "([a-z_]+)"', m.group(1))) if m else set()


def world_tables(wd):
    """Items, techniques and resource kinds of the shipped script and the world's laws file."""
    shipped = (ROOT / "living/scripts/skills.rhai").read_text()
    laws_f = wd / "laws.rhai"
    laws = laws_f.read_text() if laws_f.exists() else ""
    t = {k: rhai_names(shipped, k) | rhai_names(laws, k) for k in ("items", "know_how", "resources")}
    t["occupations"] = set()
    rep = json.loads((ROOT / "living/seeds/repertoire.json").read_text())
    for k in ("occupations", "makers"):
        t["occupations"] |= set(rep.get(k, {}).keys())
    # The world's own starting ways (`ways.json` beside the cast, merged into its seed).
    ways_f = wd / "ways.json"
    t["ways"] = json.loads(ways_f.read_text()) if ways_f.exists() else {}
    t["occupations"] |= set(t["ways"].get("occupations", {}))
    return t


def person_life(wd=None):
    """A person's life in years: `species.json`'s table, as the world's `life_years` law changes
    it. This tool cannot run Rhai: it reads the law's `person_years()` map, the form Cullet's
    laws give it in (each key an age in years that replaces the table's; docs/CULLET_RULES.md),
    and says when a world's law has another form."""
    life = json.loads((ROOT / "living/seeds/species.json").read_text())["person"]["life"]
    y = life["years"]
    out = {"child_until": life["child"] * y, "elder_from": life["elder"] * y, "old_age_from": life["old_age"] * y, "years": y, "from": "species.json"}
    laws_f = wd / "laws.rhai" if wd else None
    if laws_f and laws_f.exists() and re.search(r"\nfn life_years\(", "\n" + laws_f.read_text()):
        m = re.search(r"\nfn person_years\(\)\s*\{\s*#\{(.*?)\}\s*\}", "\n" + laws_f.read_text(), re.S)
        if not m:
            raise SystemExit(f"{laws_f}: a life_years law without a person_years() map; this check cannot read it")
        given = {k: float(v) for k, v in re.findall(r"(\w+):\s*([0-9.]+)", m.group(1))}
        keys = {"lifespan": "years", "child": "child_until", "elder": "elder_from", "old_age": "old_age_from"}
        for k, v in given.items():
            if k in keys:
                out[keys[k]] = v
        out["from"] = f"{laws_f.relative_to(ROOT)} life_years"
    return out


def hour_text(h):
    h = h % 24
    return f"{int(h):02d}:{int(round((h - int(h)) * 60)):02d}"


def place_text(p, lots):
    if p.startswith("lot:"):
        return lots[p[4:]]["name"] if p[4:] in lots else p
    return {"kelp_bed": "the Wrack Strand", "peat_bank": "the Moss", "fishing_spot": "the Weirs", "tree": "the Hanger"}.get(p, p.replace("_", " "))


def rhythm_text(r, lots):
    bed = r["wakes"] + 24 - r["sleep_h"]
    work = "; ".join(f"{hour_text(a)}-{hour_text(b)}" for a, b in r.get("works", [])) or "no set hours"
    at = " or ".join(place_text(p, lots) for p in r.get("work_at", []))
    eve = " or ".join(place_text(p, lots) for p in r.get("evening", []))
    nap = f", and sleeps again {hour_text(r['second_sleep'][0])}-{hour_text(r['second_sleep'][1])}" if r.get("second_sleep") else ""
    return f"wakes about {hour_text(r['wakes'])}, to bed about {hour_text(bed)} ({r['sleep_h']:g} hours' sleep{nap}); works {work}{' at ' + at if at else ''}; evenings at {eve or 'home'}"


def plan_of(wd, cast):
    if not cast.get("plan"):
        return None
    return json.loads((wd / cast["plan"]).read_text())


def secrets_for(cast, names):
    return [x for x in cast.get("secrets", []) if set(x["known_to"]) & set(names)]


def sheet_system(cast):
    p = cast["prompt"]
    s = SYSTEM
    for old, new in [
        ("Dead people (like Tomas) may appear in memories and stances but never in relations.", p["dead"]),
        ("(older people remember the Hunger Winter or the Oath; others last winter, trade days, Tomas's death, small family moments)", p["memories"]),
        ("people know roughly how many marks they have and what things cost.", "people know roughly how much money they have and what things cost. " + p["money"]),
    ]:
        if old not in s:
            raise SystemExit(f"sheet prompt changed; cannot place: {old[:40]}")
        s = s.replace(old, new)
    s += "\n- Situations below are facts of the world as each person in them sees them: write the person's sheet so it agrees with their side (relations, memories, stances, goals). A person who is not in a situation's people list does not know about it."
    return s + "".join("\n- " + x for x in p.get("extra", []))


def household_prompt(wd, cast, bible, s, h):
    plan = plan_of(wd, cast)
    lots = {l["id"]: l for l in plan["lots"]} if plan else {}
    names = [m["name"] for m in h["members"]]

    def line(m):
        out = f"- {m['name']} ({m['age']:g}, {m['sex']}), {m['role']}. Trade: {m.get('trade', m['occupation'])}. Knows: {', '.join(m['knows']) or 'nothing yet'}."
        out += f"\n  Wants: {m.get('wants', '')}\n  What is going on: {m.get('going_on', '')}"
        if m.get("rhythm"):
            out += f"\n  Usual day: {rhythm_text(m['rhythm'], lots)}."
        out += f"\n  Ties: {'; '.join(m.get('ties', []))}"
        if m.get("secret"):
            out += f"\n  Their own secret: {m['secret']}"
        return out

    house = f"{h.get('house', h['key'])}, a {h.get('family', '')} household" if h.get("house") else h["key"]
    sec = "\n".join(f"- {x['text']} Known ONLY to: {', '.join(x['known_to'])}." for x in secrets_for(cast, names)) or "(none)"
    return f"""# World bible
{bible}

# The whole cast (public knowledge)
{roster(cast)}

# Situations these people are part of
{situations_text(cast.get('situations', []), set(names)) or '(none)'}

# Secrets held in this household (each known ONLY to the people it names)
{sec}

# Write sheets for this household of {s['name']} ({house})
{chr(10).join(line(m) for m in h['members'])}

Write one sheet for each of: {', '.join(names)}."""


def work_span(works):
    """One working span for the seed (`works: [from, to]`) from a cast's spans: from the first
    start to the last end when that is at most 12 hours, else the longest span."""
    if not works:
        return None
    a, b = min(x for x, _ in works), max(y for _, y in works)
    if b - a <= 12:
        return [a, b]
    return list(max(works, key=lambda w: w[1] - w[0]))


def seed_rhythm(r, notes, name):
    """The seed's `rhythm` (rises, sleeps, evening_hours, works, second_sleep; seed.rs
    `SeedRhythm`) from a cast rhythm, and what the authority's limits (living_rules::rhythm:
    any rising hour, bed 8-22 h after rising, evening 0-8 h) change."""
    rises, sleeps = r["wakes"], r["wakes"] + 24 - r["sleep_h"]
    ends = [b for _, b in r.get("works", [])]
    last = max(ends) if ends else rises + 8
    evening = round(max(0.0, min(4.5, sleeps - last)), 2)
    if not (8 <= sleeps - rises <= 22):
        notes.append(f"{name}: {sleeps - rises:g} hours awake is outside the seed's 8-22")
    out = {"rises": rises, "sleeps": round(sleeps, 2), "evening_hours": evening}
    span = work_span(r.get("works", []))
    if span:
        out["works"] = span
    if r.get("second_sleep"):
        out["second_sleep"] = list(r["second_sleep"])
    return out


def resident_places(r, lots):
    """Places for the seed (`residents[].places`): work, the first evening place as `evening`,
    a second one by its own name. `lot:<id>` kinds are the plan's lots; other kinds are resource
    or structure kinds, the first that has a reachable spot winning (town.rs `seat`)."""
    out = []
    if r.get("work_at"):
        out.append({"name": "work", "kinds": r["work_at"]})
    for i, p in enumerate(r.get("evening", [])[:2]):
        out.append({"name": "evening" if i == 0 else place_text(p, lots), "kinds": [p]})
    return out


def compile_residents(wd, cast, sheets, notes):
    """The seed's residents and homes from the cast (sheets by name; None leaves them out)."""
    plan = plan_of(wd, cast)
    lots = {l["id"]: l for l in plan["lots"]} if plan else {}
    towns = []
    for s in cast["settlements"]:
        residents, homes = [], {}
        for h in s["households"]:
            if h.get("lot"):
                homes[h["key"]] = h["lot"]
            for m in h["members"]:
                r = {"name": m["name"], "age": m["age"], "household": h["key"], "occupation": m["occupation"], "knows": m["knows"], "parents": m.get("parents", [])}
                r["inventory"] = m.get("inventory", {})
                if m.get("rhythm"):
                    r["rhythm"] = seed_rhythm(m["rhythm"], notes, m["name"])
                    r["places"] = resident_places(m["rhythm"], lots)
                if sheets is not None:
                    r["sheet"] = sheets[m["name"]]
                residents.append(r)
        towns.append({"name": s["name"], "residents": residents, "homes": homes})
    return towns


def check_cast_file(wd, cast):
    """Checks a hand-written cast without a model. Returns (errors, warnings, report)."""
    errors, warn, rep = [], [], {}
    people = list(people_of(cast))
    by = {}
    for s, h, m in people:
        if m["name"] in by:
            errors.append(f"name used twice: {m['name']}")
        by[m["name"]] = (s, h, m)
    keys = [h["key"] for s in cast["settlements"] for h in s["households"]]
    if len(keys) != len(set(keys)):
        errors.append("household key used twice")
    t = world_tables(wd)
    life = person_life(wd)
    plan = plan_of(wd, cast)
    lots = {l["id"]: l for l in plan["lots"]} if plan else {}
    plan_kinds = {r["kind"] for r in plan.get("resources", [])} if plan else set()

    # Counts, by the cast's own ages and by the rules' life stages.
    c = cast.get("counts", {})
    adult_from, elder_from = c.get("adult_from", 15), c.get("elder_from", 60)
    ages = [m["age"] for _, _, m in people]
    got = {"residents": len(people), "adults": sum(a >= adult_from for a in ages), "elders": sum(a >= elder_from for a in ages), "children": sum(a < adult_from for a in ages), "households": len(keys)}
    rep["counts"] = {k: {"want": c.get(k), "got": v} for k, v in got.items()}
    for k, v in got.items():
        if k in c and c[k] != v:
            errors.append(f"count {k}: {v}, the cast says {c[k]}")
    stage = {"child": [], "adult": [], "elder": []}
    for _, _, m in people:
        stage["child" if m["age"] < life["child_until"] else "elder" if m["age"] >= life["elder_from"] else "adult"].append(m["name"])
    rep["rule_stages"] = {k: len(v) for k, v in stage.items()} | {"person_life": {k: (round(v, 1) if isinstance(v, float) else v) for k, v in life.items()}}
    young_adults = [f"{m['name']} ({m['age']:g})" for _, _, m in people if adult_from <= m["age"] < life["child_until"]]
    if young_adults:
        warn.append(f"the rules' person life puts the child stage before {life['child_until']:.1f} years, so these cast adults start as children: {', '.join(young_adults)}")
    old = [f"{m['name']} ({m['age']:g})" for _, _, m in people if m["age"] >= life["old_age_from"]]
    if old:
        warn.append(f"deaths of old age begin at {life['old_age_from']:.1f} years in the rules' person life; these residents would be seeded just short of it, and could die of age early: {', '.join(old)}")

    # Households and their lots in the plan.
    for s in cast["settlements"]:
        for h in s["households"]:
            if not plan:
                continue
            lot = lots.get(h.get("lot", ""))
            if not lot:
                errors.append(f"{h['key']}: lot {h.get('lot')!r} is not in the plan")
                continue
            if lot.get("household") != h["key"]:
                errors.append(f"{h['key']}: lot {lot['id']} is the plan's home of {lot.get('household')!r}")
            if lot.get("people") not in (None, len(h["members"])):
                errors.append(f"{h['key']}: {len(h['members'])} members, the plan's lot {lot['id']} says {lot['people']}")
            if lot.get("family") not in (None, h.get("family")):
                errors.append(f"{h['key']}: family {h.get('family')}, the plan says {lot['family']}")
        if plan:
            planned = {l["household"] for l in plan["lots"] if l.get("household")}
            missing = planned - set(keys)
            if missing:
                errors.append(f"plan households with no cast: {sorted(missing)}")

    # Kin both ways, with words that fit the relative's sex; siblings, parents, grandparents.
    kin_pairs = 0
    for n, (_, _, m) in by.items():
        for o, word in m.get("kin", {}).items():
            kin_pairs += 1
            if o not in by:
                errors.append(f"{n}: kin {o!r} is not in the cast")
                continue
            if word not in KIN:
                errors.append(f"{n}: kin word {word!r} unknown")
                continue
            rel, sex, inv = KIN[word]
            if sex and by[o][2]["sex"] != sex:
                errors.append(f"{n}: calls {o} {word}, but {o} is {by[o][2]['sex']}")
            back = by[o][2].get("kin", {}).get(n)
            if not back:
                errors.append(f"{n} -> {o} ({word}) has no way back")
            elif KIN.get(back, (None,))[0] != inv:
                errors.append(f"{n} calls {o} {word}, {o} calls {n} {back}")
        for p in m.get("parents", []):
            if p not in by:
                errors.append(f"{n}: parent {p!r} is not in the cast")
                continue
            if KIN.get(m.get("kin", {}).get(p, ""), (None,))[0] != "parent":
                errors.append(f"{n}: parent {p} is not listed as mother or father in kin")
            if by[p][2]["age"] - m["age"] < 14:
                errors.append(f"{n}: parent {p} is less than 14 years older")
        for o in by:
            if o != n and set(m.get("parents", [])) & set(by[o][2].get("parents", [])) and KIN.get(m.get("kin", {}).get(o, ""), (None,))[0] != "sibling":
                errors.append(f"{n} and {o} share a parent but are not listed as siblings")
        for p in m.get("parents", []):
            for g in by.get(p, (None, None, {}))[2].get("parents", []):
                if KIN.get(m.get("kin", {}).get(g, ""), (None,))[0] != "grandparent":
                    errors.append(f"{n}: grandparent {g} (through {p}) is not listed")
    rep["kin_links"] = kin_pairs

    # Ties that name other residents; one-sided ones across households are reported.
    full = sorted(by, key=len, reverse=True)
    named_in_ties, one_sided = 0, []
    for n, (_, h, m) in by.items():
        text = " ".join(m.get("ties", []))
        for o in full:
            if o != n and o in text:
                named_in_ties += 1
                other = " ".join(by[o][2].get("ties", []))
                if by[o][1]["key"] != h["key"] and n not in other and o not in m.get("kin", {}):
                    one_sided.append(f"{n} -> {o}")
    rep["ties_naming_residents"] = named_in_ties
    rep["one_sided_cross_household_ties"] = one_sided
    cross = {(min(n, o), max(n, o)) for n, (_, h, m) in by.items() for o in full if o != n and o in " ".join(m.get("ties", [])) and by[o][1]["key"] != h["key"]}
    rep["cross_household_pairs_tied"] = len(cross)

    # Anchors, rhythm, know-how, items, occupations.
    no_ways = {}
    for n, (_, _, m) in by.items():
        if m["age"] >= 2 and not (m.get("wants") and m.get("going_on")):
            errors.append(f"{n}: no wants or going_on anchor")
        for k in m["knows"]:
            if k not in t["know_how"]:
                errors.append(f"{n}: knows {k!r}, which the rules do not define")
        for k in m.get("inventory", {}):
            if k not in t["items"]:
                errors.append(f"{n}: carries {k!r}, which is not an item")
        if m["occupation"] not in t["occupations"] and m["occupation"] != "child":
            no_ways.setdefault(m["occupation"], []).append(n)
        r = m.get("rhythm")
        if not r:
            errors.append(f"{n}: no rhythm")
            continue
        if not (0 <= r["wakes"] < 24 and 4 <= r["sleep_h"] <= 14):
            errors.append(f"{n}: rhythm wakes {r['wakes']} / sleeps {r['sleep_h']} h out of range")
        awake_to = r["wakes"] + 24 - r["sleep_h"]
        for a, b in r.get("works", []):
            if not (a < b and (r["wakes"] <= a and b <= awake_to + 0.01 or r["wakes"] <= a + 24 and b + 24 <= awake_to + 24.01)):
                errors.append(f"{n}: works {a}-{b} is not within waking hours {hour_text(r['wakes'])}-{hour_text(awake_to)}")
        if r.get("second_sleep"):
            a, b = r["second_sleep"]
            if not (0 <= a < 24 and 0 < (b - a) % 24 <= 8):
                errors.append(f"{n}: second sleep {a}-{b} is not 0-8 hours starting within the day")
            elif any((x - a) % 24 < (b - a) % 24 for x, _ in r.get("works", [])):
                errors.append(f"{n}: second sleep {a}-{b} begins after work starts")
        if not 1 <= len(r.get("evening", [])) <= 2:
            errors.append(f"{n}: one or two evening places, not {len(r.get('evening', []))}")
        for p in r.get("work_at", []) + r.get("evening", []):
            if p.startswith("lot:"):
                if plan and p[4:] not in lots:
                    errors.append(f"{n}: place {p} is not a lot of the plan")
            elif p not in t["resources"] and p not in plan_kinds:
                errors.append(f"{n}: place kind {p!r} is neither a lot nor a resource kind")
            elif plan and p not in plan_kinds:
                warn.append(f"{n}: place kind {p!r} is a resource of the rules but the plan places none (it places {sorted(plan_kinds)}); the next lot listed is used")
    if no_ways:
        warn.append("occupations with no starting ways in repertoire.json or the seed (they start as foragers until Cullet's ways exist): " + "; ".join(f"{k} ({len(v)})" for k, v in sorted(no_ways.items())))

    # Secrets: on the knowers' sheets and nobody else's.
    for x in cast.get("secrets", []):
        for k in x["known_to"]:
            if k not in by:
                errors.append(f"secret {x['id']}: {k} is not in the cast")
                continue
            m = by[k][2]
            sit = next((y for y in cast.get("situations", []) if y["id"] == x["id"]), None)
            if not (m.get("secret") or any(tt.startswith("SECRET") for tt in m.get("ties", [])) or (sit and k in sit["people"])):
                errors.append(f"secret {x['id']}: {k} knows it but nothing on their entry says so")
        sit = next((y for y in cast.get("situations", []) if y["id"] == x["id"]), None)
        if sit and (not sit["secret"] or set(sit["people"]) != set(x["known_to"])):
            errors.append(f"secret {x['id']}: its situation must be secret and name exactly {x['known_to']}")
        for n, (_, _, m) in by.items():
            public = " ".join([m["role"]] + public_ties(m)).lower()
            private = " ".join([m.get("wants", ""), m.get("going_on", ""), m.get("secret", "")] + m.get("ties", [])).lower()
            sides = " ".join(y["sides"].get(n, "") for y in cast.get("situations", [])).lower()
            for mk in x.get("markers", []):
                if mk in public:
                    errors.append(f"secret {x['id']}: '{mk}' in {n}'s public role or ties")
                if n not in x["known_to"] and (mk in private or mk in sides):
                    errors.append(f"secret {x['id']}: '{mk}' on {n}'s entry, who does not know it")
    # The bible goes into every household's prompt, so it must not give a secret away either.
    bible_f = wd / "bible.md"
    bible = bible_f.read_text().lower() if bible_f.exists() else ""
    for x in cast.get("secrets", []):
        for mk in x.get("markers", []):
            if mk in bible:
                errors.append(f"secret {x['id']}: '{mk}' is in the bible, which every household sees")
    rep["secrets"] = {x["id"]: x["known_to"] for x in cast.get("secrets", [])}

    # Situations and tensions.
    sit_ids = set()
    for x in cast.get("situations", []):
        sit_ids.add(x["id"])
        for p in x["people"]:
            if p not in by:
                errors.append(f"situation {x['id']}: {p} is not in the cast")
            if not x["sides"].get(p):
                errors.append(f"situation {x['id']}: no side for {p}")
        for p in x["sides"]:
            if p not in x["people"]:
                errors.append(f"situation {x['id']}: a side for {p}, who is not in it")
    for x in cast.get("tensions", []):
        for sid in x.get("situations", []):
            if sid not in sit_ids:
                errors.append(f"tension {x['name']}: no situation {sid}")
        inside = {p for y in cast.get("situations", []) if y["id"] in x.get("situations", []) for p in y["people"]}
        for p in x["carried_by"]:
            if p not in by:
                errors.append(f"tension {x['name']}: {p} is not in the cast")
            elif p not in inside:
                errors.append(f"tension {x['name']}: {p} carries it but is in none of its situations")
    rep["situations"] = len(sit_ids)
    rep["tensions"] = len(cast.get("tensions", []))

    # What the compile would bind and what the seed's clamps change.
    notes = []
    towns = compile_residents(wd, cast, None, notes)
    rep["homes"] = {t_["name"]: t_["homes"] for t_ in towns}
    warn += notes
    return errors, warn, rep


def print_checks(errors, warn, rep):
    c = rep["counts"]
    print("counts: " + ", ".join(f"{k} {v['got']}" + (f" (want {v['want']})" if v["want"] is not None else "") for k, v in c.items()))
    rs = rep["rule_stages"]
    print(f"rule life stages ({rs['person_life']['from']}, person: child < {rs['person_life']['child_until']} y, elder from {rs['person_life']['elder_from']} y, old-age deaths from {rs['person_life']['old_age_from']} y): child {rs['child']}, adult {rs['adult']}, elder {rs['elder']}")
    print(f"kin links {rep['kin_links']} (each checked both ways); ties naming residents {rep['ties_naming_residents']}; household pairs tied across houses {rep['cross_household_pairs_tied']}; one-sided cross-household ties {len(rep['one_sided_cross_household_ties'])}")
    print(f"situations {rep['situations']}, tensions {rep['tensions']}, secrets {len(rep['secrets'])}: " + "; ".join(f"{k} known to {', '.join(v)}" for k, v in rep["secrets"].items()))
    for town, homes in rep["homes"].items():
        print(f"homes ({town}, SeedTown.homes): {len(homes)} households bound: " + ", ".join(f"{k}->{v}" for k, v in homes.items()))
    for w in warn:
        print("  warning:", w)
    for e in errors:
        print("  ERROR:", e)
    print(f"{len(errors)} errors, {len(warn)} warnings")


def dry_run(a, wd, cast, bible):
    """Everything the drafting would do, without a model and without the network."""
    errors, warn, rep = check_cast_file(wd, cast)
    print_checks(errors, warn, rep)
    out = Path(a.out) if a.out else None
    if out:
        (out / "prompts").mkdir(parents=True, exist_ok=True)
    models = json.loads(Path(env_models_path()).read_text())
    prof = models["profiles"].get(a.profile)
    if not prof:
        sys.exit(f"profile {a.profile!r} is not in the models config")
    sheets_dir = wd / "sheets"
    system = sheet_system(cast) if cast.get("prompt") else SYSTEM
    rows, total_in, total_out = [], 0, 0
    for s in cast["settlements"]:
        for h in s["households"]:
            if (sheets_dir / f"{h['key']}.json").exists():
                continue
            user = household_prompt(wd, cast, bible, s, h) if cast.get("prompt") else None
            if user is None:
                continue
            p_tokens = (len(system) + len(user)) / 4
            o_tokens = OUT_PER_SHEET * len(h["members"])
            total_in += p_tokens
            total_out += o_tokens
            secrets = [x["id"] for x in secrets_for(cast, [m["name"] for m in h["members"]])]
            rows.append((h["key"], len(h["members"]), len(user), round(p_tokens), round(o_tokens), secrets))
            if out:
                (out / "prompts" / f"{h['key']}.txt").write_text(f"# system\n{system}\n\n# user\n{user}\n")
    n = sum(len(h["members"]) for s in cast["settlements"] for h in s["households"])
    shared = (len(system) + len(bible) + len(roster(cast))) / 4
    print(f"\nwould draft {len(rows)} households ({sum(r[1] for r in rows)} sheets) with profile {a.profile} ({prof['model']}), reasoning effort {a.effort or 'not sent'}, one call each:")
    for k, members, chars, pt, ot, sec in rows:
        print(f"  {k:<11} {members} sheets, prompt {chars:>6} chars (~{pt} tokens), ~{ot} output tokens" + (f", secrets: {', '.join(sec)}" if sec else ""))
    fills = FILLS_PER_PERSON * n
    fill_in = fills * (shared + 400)
    fill_out = fills * OUT_PER_FILL
    print(f"then about {fills:.0f} small calls to fill one-sided family or named ties (the island's rate, {FILLS_PER_PERSON:.2f} a person), each ~{shared + 400:.0f} prompt tokens")
    price = PRICES_EUR.get(prof["model"])
    est = {"profile": a.profile, "model": prof["model"], "effort": a.effort, "calls": len(rows) + round(fills), "sheet_calls": len(rows), "fill_calls": round(fills), "prompt_tokens": round(total_in + fill_in), "shared_prefix_tokens": round(shared), "output_tokens": round(total_out + fill_out)}
    if price:
        def eur(cached_share):
            tin = total_in + fill_in
            return (tin * (1 - cached_share) * price[0] + tin * cached_share * price[1] + (total_out + fill_out) * price[2]) / 1e6
        est["eur_no_cache"] = round(eur(0.0), 3)
        est["eur_cached_80"] = round(eur(0.8), 3)
        est["eur_with_retries"] = round(eur(0.0) * 1.3, 3)
        print(f"estimate: {est['calls']} calls, ~{est['prompt_tokens']:,} prompt tokens (~{est['shared_prefix_tokens']:,} of each call is the same bible, cast and rules), ~{est['output_tokens']:,} output tokens")
        print(f"  EUR {est['eur_cached_80']:.2f} if 80% of the prompt is cached, {est['eur_no_cache']:.2f} with no cache, {est['eur_with_retries']:.2f} with no cache and 30% redrafts (prices: docs/MODEL_COST.md, {prof['model']} in/cached/out {price[0]}/{price[1]}/{price[2]} EUR per M)")
    else:
        print(f"no price for {prof['model']} in this tool; see docs/MODEL_COST.md")
    notes = []
    towns = compile_residents(wd, cast, None, notes)
    if out:
        (out / "compile-preview.json").write_text(json.dumps({"into": f"living/seeds/{cast.get('into', a.world)}.json", "towns": towns, "note": "residents without sheets, as the compile would write them once sheets exist; not written to the seed"}, indent=1, ensure_ascii=False) + "\n")
        (out / "estimate.json").write_text(json.dumps(est, indent=1) + "\n")
        (out / "checks.json").write_text(json.dumps({"errors": errors, "warnings": warn, "report": rep}, indent=1, ensure_ascii=False) + "\n")
    t = towns[0]
    print(f"compile would write into living/seeds/{cast.get('into', a.world)}.json, town {t['name']}: {len(t['residents'])} residents with rhythm and places, homes for {len(t['homes'])} households (sheets missing: {sum(1 for s in cast['settlements'] for h in s['households'] if not (sheets_dir / (h['key'] + '.json')).exists())} households, so --compile-only would stop)")
    print("no model was called; no key was read")
    return 1 if errors else 0


def env_models_path():
    return os.environ.get("LIVING_MODELS", str(ROOT / "living/configs/models.json"))


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
    # A hand-written cast with anchors (Cullet): checks and a dry run, neither calls a model.
    ap.add_argument("--check", action="store_true", help="check the cast (kin, lots, counts, rhythm, secrets) and stop")
    ap.add_argument("--dry-run", action="store_true", help="check, build every prompt, estimate the spend and preview the compile; no model, no network")
    ap.add_argument("--out", default="", help="with --dry-run: a directory for the prompts, the estimate and the compile preview")
    a = ap.parse_args()
    wd = ROOT / "living/seeds/worlds" / a.world
    if (wd / "world.json").exists():
        sys.exit(lives(a, wd))
    cast = json.loads((wd / "cast.json").read_text())
    bible = (wd / "bible.md").read_text()
    if a.check:
        errors, warn, rep = check_cast_file(wd, cast)
        print_checks(errors, warn, rep)
        sys.exit(1 if errors else 0)
    if a.dry_run:
        sys.exit(dry_run(a, wd, cast, bible))
    names = {m["name"] for _, _, m in people_of(cast)}
    sheets_dir = wd / "sheets"
    if cast.get("prompt"):
        global LOG_PATH
        LOG_PATH = wd / "authoring-log.jsonl"
        if not a.compile_only:
            errors, warn, rep = check_cast_file(wd, cast)
            if errors:
                print_checks(errors, warn, rep)
                sys.exit("the cast has errors; fix them before drafting")
    sheets_dir.mkdir(exist_ok=True)

    if not a.compile_only:
        todo = [(s, h) for s in cast["settlements"] for h in s["households"] if not (sheets_dir / f"{h['key']}.json").exists()]
        print(f"drafting {len(todo)} households with {a.profile}", flush=True)
        with concurrent.futures.ThreadPoolExecutor(a.jobs) as ex:
            futs = {ex.submit(draft_household, wd, cast, bible, s, h, a.profile, a.effort): h for s, h in todo}
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
                v = logged_call(a.profile, sheet_system(cast), user, a.effort, f"ties:{o}") if cast.get("prompt") else model_call(a.profile, SYSTEM, user, effort="low")
            except RuntimeError as e:
                notes.append(f"{o}: fill failed: {e}")
                continue
            f = sheets_dir / f"{h['key']}.json"
            raw = json.loads(f.read_text())
            raw[o].setdefault("relations", []).extend([r for r in v.get("relations", []) if r.get("name") in others])
            f.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n")
            sheets[o] = check_sheet(o, raw[o], names, notes)

    if cast.get("into"):
        # Merge into the world's existing seed (Cullet's is written by cullet_plan.py): each
        # settlement's residents and homes; the rest of the seed and the town are kept.
        out = ROOT / "living/seeds" / f"{cast['into']}.json"
        seed = json.loads(out.read_text())
        for t in compile_residents(wd, cast, sheets, notes):
            town = next((x for x in seed.get("towns", []) + seed.get("villages", []) if x["name"] == t["name"]), None)
            if town is None:
                sys.exit(f"{out.name} has no settlement {t['name']}")
            town["residents"], town["homes"] = t["residents"], t["homes"]
        out.write_text(json.dumps(seed, indent=1, ensure_ascii=False) + "\n")
        print(f"wrote {out.relative_to(ROOT)}: {len(sheets)} residents")
        for n in notes[:30]:
            print("  note:", n)
        return
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
