"""Interpret one actor's retained perceptions into a mind log with a language model.

Reads only the selected actor's perception events from an owner snapshot. The model may create
concepts, claims and stances; evidence items are generated from perceptions the actor had, so the
model can cite but not invent them. Every exchange and rejected output is journaled.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import time
import urllib.request
from pathlib import Path
from typing import Any

from .mind import MindLog, MindState, parse_event
from .model import identifier

BASE_URL = "https://codex.carlid.dev/v1"
MODEL = "gpt-5.6-luna"
KEY_ENV = "CARLID_NPC_API_KEY"
DEADLINE_S = 240
ALWAYS_SHOWN = {"speech", "prior_report"}

SYSTEM_V1 = """You maintain the private mind of {name}, a character in a survival settlement simulation. \
You receive {name}'s current mind and a batch of new perceptions. Return only the additions to the mind.

The mind is a graph owned by {name} alone:
- concepts: handles {name} uses for people, places, things, relations and categories. Use IDs starting \
"c:" for entities and categories and "rel:" for relations. Reuse existing concepts; create one only for \
something new. Labels are {name}'s own words.
- claims: propositions. A predicate (a relation concept or a core concept) plus 1-8 named roles, each \
pointing to a concept or an existing claim. Choose role names that make the claim readable, such as \
speaker, content, builder, place, thing, condition, time. A claim alone says nothing about whether it is true.
- stances: {name}'s credence from 0 to 100 that a claim is true, citing perceptions (percept:ID) or other \
claims (k:ID) with bearing "supports" or "opposes". Each claim has at most one current stance. To change \
credence in a claim that has one, add a stance whose "revises" is that current stance ID.

Fixed concepts: core:self is {name}; core:instance_of has roles instance and category; core:same_as has \
roles a and b; core:asserted has roles speaker and content (a claim), optionally audience.

Rules:
- Hearing is not believing. For speech, add a core:asserted claim with a stance on how sure {name} is \
that it was said, and a separate stance on the content that is {name}'s own judgment. The content stance \
may cite the asserted claim.
- Cite only perceptions listed in this or earlier batches. Do not invent perceptions, or knowledge {name} \
could not have.
- Record what {name} would care about or act on: commitments and whether they are kept, who does what, \
resources, safety, trust. Skip repetition that changes nothing.
- Revise earlier stances when new perceptions bear on them.
- A note is a short first-person reason. Put meaning in the structure, not only in the note.
- If the batch changes nothing, return empty arrays.
- New IDs must not already exist. Stance IDs are "s:" followed by a new name.

Reply with exactly one JSON object and nothing else:
{{"concepts":[{{"id":"c:...","label":"..."}}],
 "claims":[{{"id":"k:...","predicate":"rel:... or core:...","roles":{{"role":"concept or claim ID"}}}}],
 "stances":[{{"id":"s:...","claim":"k:...","credence":0,"cites":[{{"ref":"percept:ID or k:...","bearing":"supports"}}],"revises":null,"note":"..."}}]}}"""

SYSTEM_V2 = """You maintain the private mind of {name}, a character in a survival settlement simulation. \
You receive {name}'s current mind and a batch of new perceptions. Return only the additions to the mind.

Perceptions are already kept verbatim as evidence that can be cited later. Do not restate them as claims. \
The mind holds {name}'s interpretations: what {name} concludes, expects, suspects or has been told, and \
how sure {name} is.

The mind is a graph owned by {name} alone:
- concepts: handles {name} uses for people, places, things, relations and categories. Use IDs starting \
"c:" for entities and categories and "rel:" for relations. Reuse existing concepts; create one only for \
something new. Labels are {name}'s own words. Numbers and ticks are never concepts.
- claims: propositions. A predicate (a relation concept or a core concept) plus 1-8 named roles. A role \
points to a concept or an existing claim, or holds a literal integer such as "amount": 8 or "by_tick": 12. \
Choose role names that make the claim readable. A claim alone says nothing about whether it is true.
- stances: {name}'s credence from 0 to 100 that a claim is true, citing perceptions (percept:ID) or other \
claims (k:ID) with bearing "supports" or "opposes". Each claim has at most one current stance. To change \
credence in a claim that has one, add a stance whose "revises" is that current stance ID.

Fixed concepts: core:self is {name}; core:instance_of has roles instance and category; core:same_as has \
roles a and b; core:asserted has roles speaker and content (a claim), optionally audience.

Rules:
- Hearing is not believing. For speech, add a core:asserted claim with a stance on how sure {name} is \
that it was said, and a separate stance on the content that is {name}'s own judgment. The content stance \
may cite the asserted claim.
- Good claims are ones that would change what {name} does or whom {name} trusts: commitments and whether \
they are kept, patterns in who does what, how resources are trending, needs, risks, plans, and \
differences between what someone said and what {name} saw.
- Prefer revising an existing stance over adding a near-duplicate claim.
- Add at most {max_claims} new claims per batch; usually far fewer. Returning nothing is fine.
- Cite only perceptions listed in this or earlier batches. Do not invent perceptions, or knowledge {name} \
could not have.
- A note is a short first-person reason. Put meaning in the structure, not only in the note.
- New IDs must not already exist. Stance IDs are "s:" followed by a new name.

Reply with exactly one JSON object and nothing else:
{{"concepts":[{{"id":"c:...","label":"..."}}],
 "claims":[{{"id":"k:...","predicate":"rel:... or core:...","roles":{{"role":"concept or claim ID, or an integer"}}}}],
 "stances":[{{"id":"s:...","claim":"k:...","credence":0,"cites":[{{"ref":"percept:ID or k:...","bearing":"supports"}}],"revises":null,"note":"..."}}]}}"""

PROMPTS = {"v1": SYSTEM_V1, "v2": SYSTEM_V2}


def perceptions(snapshot: dict[str, Any], actor: int) -> tuple[str, list[dict[str, Any]]]:
    world = snapshot.get("world", snapshot)
    player = next((p for p in world.get("players", []) if p.get("id") == actor), None)
    if player is None:
        raise ValueError(f"actor {actor} not in snapshot")
    events = sorted(
        (e for e in snapshot.get("events", []) if e.get("kind") == "perception" and e.get("actor") == actor),
        key=lambda e: e["id"],
    )
    return player["name"], events


def render(event: dict[str, Any], names: dict[int, str]) -> str:
    data, content = event["data"], event["data"].get("content") or {}
    kind, source = data.get("kind"), data.get("from")
    who = names.get(source, f"person #{source}")
    if kind == "speech":
        return f'{content.get("speaker", who)} said: "{content.get("text", "")}"'
    if kind == "prior_report":
        claim = content.get("claim", {})
        danger = " (dangerous)" if claim.get("danger") else ""
        return f"I remember{danger} about cell {claim.get('location')}: {claim.get('text', '')}"
    if kind == "seen_player":
        return f"I see {content.get('name', who)} at cell {content.get('position')}"
    if kind == "site":
        return f"cell {data.get('location')}: food {content.get('food')}, shelter {content.get('shelter')}"
    if kind == "own_result":
        return f"my {content.get('skill')} {content.get('status')}"
    if kind == "shelter_work":
        return f"{who} added {content.get('amount')} to the shelter, now {content.get('shelter_after')}"
    if kind == "food_growth":
        return f"food at cell {data.get('location')} grew by {content.get('food_delta')}, now {content.get('food_after')}"
    return f"{kind}: {json.dumps(content, sort_keys=True)[:300]}"


def digest(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep each perception whose rendering changed on its channel; speech and memories always."""
    names: dict[int, str] = {}
    last: dict[tuple[Any, ...], str] = {}
    shown = []
    for event in events:
        data = event["data"]
        if data.get("kind") == "seen_player" and data.get("from") is not None:
            names[data["from"]] = (data.get("content") or {}).get("name", names.get(data["from"]))
        line = render(event, names)
        channel = (data.get("kind"), data.get("from"), data.get("location"))
        if data.get("kind") in ALWAYS_SHOWN or last.get(channel) != line:
            last[channel] = line
            shown.append({"ref": f"percept:{event['id']}", "tick": event["tick"],
                          "kind": data.get("kind"), "text": line})
    return shown


def batches(shown: list[dict[str, Any]], window: int) -> list[list[dict[str, Any]]]:
    groups: dict[int, list[dict[str, Any]]] = {}
    for item in shown:
        groups.setdefault(item["tick"] // window, []).append(item)
    return [groups[key] for key in sorted(groups)]


def describe(events: list[dict[str, Any]], state: MindState) -> str:
    """The actor's whole current mind, rendered from its own log."""
    labels = {e["id"]: e["label"] for e in events if e["op"] == "concept"}
    evidence = {e["id"]: e for e in events if e["op"] == "evidence"}
    stances = {e["id"]: e for e in events if e["op"] == "stance"}
    cited: dict[str, list[dict[str, str]]] = {}
    for stance in stances.values():
        cited.setdefault(stance["claim"], []).extend(stance["cites"])
    lines = ["Concepts:"] + [f"  {item}: {label}" for item, label in labels.items()]
    lines.append("Claims:")
    for claim in (e for e in events if e["op"] == "claim"):
        roles = ", ".join(
            f"{role}={target}" if type(target) is int else f"{role}={labels.get(target, '«' + target + '»')}"
            for role, target in sorted(claim["roles"].items())
        )
        current = state.current.get(claim["id"])
        belief = (f"current stance {current} credence {stances[current]['credence']}"
                  if current else "no stance")
        refs = "; ".join(f"{c['bearing']} {c['ref']}" for c in cited.get(claim["id"], []))
        lines.append(f"  [{claim['id']}] {labels[claim['predicate']]}({roles}) {belief}"
                     + (f"; {refs}" if refs else ""))
    if evidence:
        lines.append("Perceptions you have relied on:")
        lines += [f"  {item} [tick {e['tick']}] {e['summary']}" for item, e in evidence.items()]
    return "\n".join(lines)


def complete(messages: list[dict[str, str]]) -> dict[str, Any]:
    body = {"model": MODEL, "stream": True, "messages": messages}
    request = urllib.request.Request(
        f"{BASE_URL}/chat/completions", data=json.dumps(body).encode(),
        headers={"Authorization": "Bearer " + os.environ[KEY_ENV], "Content-Type": "application/json",
                 "Accept": "text/event-stream", "User-Agent": "slop-art-online-concept-graph/0.1"},
    )
    started = time.monotonic()
    parts, usage = [], None
    with urllib.request.urlopen(request, timeout=DEADLINE_S) as response:
        for raw in response:
            line = raw.decode("utf-8").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            chunk = json.loads(data)
            usage = chunk.get("usage") or usage
            for choice in chunk.get("choices", []):
                parts.append((choice.get("delta") or {}).get("content") or "")
    return {"text": "".join(parts), "elapsed_s": round(time.monotonic() - started, 2), "usage": usage}


def _object(text: str) -> dict[str, Any]:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("reply contains no JSON object")
    value = json.loads(text[start:end + 1])
    if not isinstance(value, dict) or set(value) - {"concepts", "claims", "stances"}:
        raise ValueError("reply must have only concepts, claims and stances")
    return value


def _ordered_claims(claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Order new claims so claims referenced by roles come first."""
    pending = {claim.get("id"): claim for claim in claims}
    ordered: list[dict[str, Any]] = []
    while pending:
        ready = [c for c in pending.values()
                 if not any(t in pending and t != c.get("id") for t in (c.get("roles") or {}).values())]
        if not ready:
            ready = list(pending.values())
        for claim in ready:
            ordered.append(claim)
            pending.pop(claim.get("id"))
    return ordered


def to_events(reply: dict[str, Any], seen: dict[str, dict[str, Any]], state: MindState,
              start: int, tick: int, max_claims: int | None = None) -> list[dict[str, Any]]:
    if max_claims is not None and len(reply.get("claims") or []) > max_claims:
        raise ValueError(f"at most {max_claims} new claims are allowed per batch")
    raw: list[dict[str, Any]] = []
    for concept in reply.get("concepts") or []:
        raw.append({"op": "concept", **concept})
    stances = reply.get("stances") or []
    refs = {cite.get("ref") for stance in stances for cite in stance.get("cites") or []
            if isinstance(cite, dict)}
    for ref in sorted(r for r in refs if isinstance(r, str) and r.startswith("percept:")):
        if ref in state.kinds:
            continue
        if ref not in seen:
            raise ValueError(f"cites a perception the actor has not been shown: {ref}")
        item = seen[ref]
        raw.append({"op": "evidence", "id": ref, "kind": item["kind"], "tick": item["tick"],
                    "summary": item["text"]})
    for claim in _ordered_claims(reply.get("claims") or []):
        raw.append({"op": "claim", **claim})
    for stance in stances:
        raw.append({"op": "stance", "tick": tick, **{k: v for k, v in stance.items() if k != "tick"}})
    events = []
    trial = copy.deepcopy(state)
    for seq, item in enumerate(raw, start):
        event = parse_event({"seq": seq, **item})
        trial.apply(event)
        events.append(event)
    return events


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("--actor", type=int, required=True)
    parser.add_argument("--run", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--window", type=int, default=6, help="ticks per interpretation batch")
    parser.add_argument("--max-batches", type=int)
    parser.add_argument("--load", action="store_true", help="append accepted batches to Neo4j")
    parser.add_argument("--prompt", choices=sorted(PROMPTS), default="v2")
    parser.add_argument("--max-claims", type=int, default=10, help="claim budget per batch (v2 prompt)")
    args = parser.parse_args()
    run = identifier(args.run, "run")
    if KEY_ENV not in os.environ:
        parser.error(f"set {KEY_ENV}")

    name, events = perceptions(json.loads(args.snapshot.read_text()), args.actor)
    shown = digest(events)
    groups = batches(shown, args.window)[: args.max_batches]
    out = args.out / f"actor-{args.actor}"
    out.mkdir(parents=True, exist_ok=False)
    (out / "digest.json").write_text(json.dumps(
        {"actor": args.actor, "name": name, "perceptions": len(events), "shown": shown}, indent=2))

    log: list[dict[str, Any]] = []
    state = MindState()
    seed = [{"op": "concept", "id": "core:self", "label": f"{name} (me)"},
            {"op": "concept", "id": "core:instance_of", "label": "is a kind of"},
            {"op": "concept", "id": "core:same_as", "label": "is the same as"},
            {"op": "concept", "id": "core:asserted", "label": "said"}]
    batch_logs = [[parse_event({"seq": seq, **item}) for seq, item in enumerate(seed, 1)]]
    for event in batch_logs[0]:
        state.apply(event)
        log.append(event)

    store = None
    if args.load:
        from neo4j import GraphDatabase

        from .mind_store import MindStore

        driver = GraphDatabase.driver(os.environ.get("CONCEPT_GRAPH_NEO4J_URI", "bolt://127.0.0.1:7688"),
                                      auth=("neo4j", os.environ["CONCEPT_GRAPH_NEO4J_PASSWORD"]))
        store = MindStore(driver)
        store.initialize()
        store.load(MindLog(run, args.actor, tuple(batch_logs[0])))

    seen: dict[str, dict[str, Any]] = {}
    budget = args.max_claims if args.prompt != "v1" else None
    system = PROMPTS[args.prompt].format(name=name, max_claims=budget)
    for number, group in enumerate(groups, 1):
        seen.update({item["ref"]: item for item in group})
        first, last = group[0]["tick"], group[-1]["tick"]
        user = (f"Current mind of {name}:\n{describe(log, state)}\n\n"
                f"New perceptions (ticks {first}-{last}):\n"
                + "\n".join(f"{item['ref']} [tick {item['tick']}] {item['text']}" for item in group))
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        attempts, accepted = [], None
        for _ in range(2):
            reply = complete(messages)
            attempt = {"reply": reply, "error": None}
            attempts.append(attempt)
            try:
                accepted = to_events(_object(reply["text"]), seen, state, state.head + 1, last, budget)
                break
            except (ValueError, KeyError, TypeError) as error:
                attempt["error"] = str(error)
                messages = messages[:2] + [
                    {"role": "assistant", "content": reply["text"]},
                    {"role": "user", "content": f"That reply was rejected: {error}. "
                                                "Return a corrected complete JSON object."},
                ]
        journal = {"batch": number, "ticks": [first, last], "perceptions": [i["ref"] for i in group],
                   "request": {"model": MODEL, "base_url": BASE_URL, "prompt": args.prompt,
                               "max_claims": budget, "messages": messages},
                   "attempts": attempts, "accepted": accepted}
        (out / f"batch-{number:02d}.json").write_text(json.dumps(journal, indent=2))
        if accepted is None:
            print(f"batch {number} ticks {first}-{last}: rejected ({attempts[-1]['error']})")
            continue
        for event in accepted:
            state.apply(event)
            log.append(event)
        if accepted:
            batch_logs.append(accepted)
            if store is not None:
                store.load(MindLog(run, args.actor, tuple(accepted)))
        ops = {op: sum(e["op"] == op for e in accepted) for op in ("concept", "evidence", "claim", "stance")}
        print(f"batch {number} ticks {first}-{last}: {len(group)} perceptions, "
              f"{len(attempts)} attempt(s), added {ops}", flush=True)

    for number, batch in enumerate(batch_logs):
        (out / f"mind-{number:02d}.json").write_text(json.dumps(
            {"run": run, "actor": args.actor, "events": batch}, indent=1))
    (out / "mind.txt").write_text(describe(log, state) + "\n")
    if store is not None:
        store.driver.close()


if __name__ == "__main__":
    main()
