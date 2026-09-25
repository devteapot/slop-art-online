"""One-time adapter from an owner snapshot's current mind, not an audit replay."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .model import Perspective


def _topic_id(topic: str) -> str:
    return hashlib.sha256(topic.encode("utf-8")).hexdigest()[:20]


def current_mind(snapshot: dict[str, Any], run: str, actor: int) -> Perspective:
    world = snapshot.get("world", snapshot)
    players = world.get("players", [])
    player = next((p for p in players if p.get("id") == actor), None)
    if player is None:
        raise ValueError(f"actor {actor} not in snapshot")
    memories = {
        memory.get("source"): memory
        for memory in player.get("memories", []) + player.get("site_observations", [])
        if isinstance(memory, dict)
    }

    def source(source_id: Any) -> list[dict[str, str]]:
        if type(source_id) is not int or source_id < 0:
            raise ValueError("current mind contains a claim without a numeric source")
        memory = memories.get(source_id)
        if memory is None:
            kind = "unresolved_personal_citation"
            summary = "Source is cited in current mind but absent from retained personal memories"
        else:
            kind = "personal_perception"
            summary = json.dumps(
                {"kind": memory.get("kind"), "content": memory.get("content")},
                sort_keys=True,
            )[:1280]
        return [{"id": f"source:{source_id}", "kind": kind, "summary": summary}]

    claims: list[dict[str, Any]] = []
    for index, known in enumerate(player.get("beliefs", [])):
        belief = known["claim"]
        location = belief["location"]
        claims.append({
            "id": f"legacy-belief:{index}",
            "subject": {"id": f"location:{location}", "kind": "location", "label": f"Location {location}"},
            "relation": "has_danger",
            "object": {"id": "concept:danger", "kind": "condition", "label": "danger"},
            "confidence": known["confidence"],
            "polarity": "positive" if belief["danger"] else "negative",
            "note": belief["text"],
            "evidence": source(known["source"]),
        })
    for index, holding in enumerate(player.get("knowledge", [])):
        record = holding["record"]
        topic = record["topic"]
        claims.append({
            "id": f"legacy-holding:{index}",
            "subject": {"id": f"topic:{_topic_id(topic)}", "kind": "topic", "label": topic},
            "relation": "has_report",
            "object": {"id": f"record:{record['id']}", "kind": "report", "label": record["text"][:240]},
            "confidence": holding.get("confidence") if holding.get("confidence") is not None else record["confidence"],
            "polarity": "uncertain" if holding.get("interpretation") is None else "positive",
            "note": holding.get("interpretation") or "Held report; not yet personally assessed",
            "evidence": source(holding["source"]),
        })
    for other, trust in player.get("relationships", {}).items():
        claims.append({
            "id": f"legacy-relationship:{other}",
            "subject": {"id": f"person:{actor}", "kind": "person", "label": f"Person {actor}"},
            "relation": "trusts",
            "object": {"id": f"person:{other}", "kind": "person", "label": f"Person {other}"},
            "confidence": 100,
            "polarity": "positive" if trust > 0 else "negative" if trust < 0 else "uncertain",
            "note": f"Legacy trust score {trust}; no specific causal source in this map",
            "evidence": [{"id": f"legacy-relationship:{other}", "kind": "legacy_state", "summary": "Current relationship map; source provenance unavailable"}],
        })
    return Perspective.parse({"run": run, "actor": actor, "claims": claims})
