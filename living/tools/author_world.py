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

Usage: living/tools/author_world.py <world> [--profile luna] [--jobs 4] [--compile-only]
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("world")
    ap.add_argument("--profile", default="luna")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--compile-only", action="store_true")
    a = ap.parse_args()
    wd = ROOT / "living/seeds/worlds" / a.world
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
                residents.append({"name": m["name"], "age": m["age"], "household": h["key"], "occupation": m["occupation"], "knows": m["knows"], "parents": m.get("parents", []), "sheet": sheets[m["name"]]})
        t = {"name": s["name"], "character": s["character"], "walled": s["walled"], "occupations": {}, "stores": s["stores"], "resources": s.get("resources", {}), "ledger": s["ledger"], "residents": residents}
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
