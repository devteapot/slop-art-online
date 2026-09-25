"""Actor-owned mind log: concepts, open-role claims, evidence and credence revisions."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from .model import identifier, text

MAX_BATCH = 256
MAX_ITEMS = 1024
MAX_ROLES = 8
MAX_CITES = 8
MAX_LITERAL = 1_000_000_000

# Fixed meanings that mechanics and queries may rely on. Everything else is actor-defined.
CORE_CONCEPTS = frozenset({"core:self", "core:instance_of", "core:same_as", "core:asserted"})
CORE_ROLES = {
    "core:instance_of": {"instance": "concept", "category": "concept"},
    "core:same_as": {"a": "concept", "b": "concept"},
    "core:asserted": {"speaker": "concept", "content": "claim"},
}
FIELDS = {
    "concept": {"id", "label"},
    "evidence": {"id", "kind", "tick", "summary", "involves"},
    "claim": {"id", "predicate", "roles"},
    "stance": {"id", "claim", "credence", "tick", "cites", "revises", "note"},
}


def _tick(value: Any, name: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} must be a nonnegative integer")
    return value


def _roles(value: Any, name: str, minimum: int, literals: bool = False) -> dict[str, str | int]:
    if not isinstance(value, dict) or not minimum <= len(value) <= MAX_ROLES:
        raise ValueError(f"{name} must map {minimum}–{MAX_ROLES} role names to item IDs")
    roles: dict[str, str | int] = {}
    for role, target in value.items():
        role = identifier(role, f"{name} role")
        if literals and type(target) is int:
            if abs(target) > MAX_LITERAL:
                raise ValueError(f"{name}.{role} literal must be within ±{MAX_LITERAL}")
            roles[role] = target
        else:
            roles[role] = identifier(target, f"{name}.{role}")
    return roles


def parse_event(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("event must be an object")
    seq = value.get("seq")
    if type(seq) is not int or seq < 1:
        raise ValueError("event.seq must be a positive integer")
    op = value.get("op")
    if op not in FIELDS:
        raise ValueError(f"event {seq} has an unknown op")
    unknown = set(value) - FIELDS[op] - {"seq", "op"}
    if unknown:
        raise ValueError(f"event {seq} has unknown fields: {', '.join(sorted(unknown))}")
    event: dict[str, Any] = {"seq": seq, "op": op, "id": identifier(value.get("id"), "event.id")}
    if op == "concept":
        event["label"] = text(value.get("label"), "concept.label", 240)
    elif op == "evidence":
        event["kind"] = identifier(value.get("kind"), "evidence.kind")
        event["tick"] = _tick(value.get("tick"), "evidence.tick")
        event["summary"] = text(value.get("summary"), "evidence.summary")
        event["involves"] = _roles(value.get("involves", {}), "evidence.involves", 0)
    elif op == "claim":
        event["predicate"] = identifier(value.get("predicate"), "claim.predicate")
        event["roles"] = _roles(value.get("roles"), "claim.roles", 1, literals=True)
    else:
        event["claim"] = identifier(value.get("claim"), "stance.claim")
        credence = value.get("credence")
        if type(credence) is not int or not 0 <= credence <= 100:
            raise ValueError("stance.credence must be an integer from 0 to 100")
        event["credence"] = credence
        event["tick"] = _tick(value.get("tick"), "stance.tick")
        cites = value.get("cites")
        if not isinstance(cites, list) or not 1 <= len(cites) <= MAX_CITES:
            raise ValueError(f"stance requires 1–{MAX_CITES} citations")
        event["cites"] = []
        for cite in cites:
            if not isinstance(cite, dict) or set(cite) != {"ref", "bearing"}:
                raise ValueError("citation must have exactly ref and bearing")
            if cite["bearing"] not in ("supports", "opposes"):
                raise ValueError("citation bearing must be supports or opposes")
            event["cites"].append({"ref": identifier(cite["ref"], "cite.ref"), "bearing": cite["bearing"]})
        if len({cite["ref"] for cite in event["cites"]}) != len(event["cites"]):
            raise ValueError("stance cites the same item twice")
        revises = value.get("revises")
        event["revises"] = None if revises is None else identifier(revises, "stance.revises")
        note = value.get("note", "")
        if not isinstance(note, str) or len(note) > 1280:
            raise ValueError("stance.note must be at most 1280 characters")
        event["note"] = note
    return event


def payload(event: dict[str, Any]) -> str:
    return json.dumps(event, sort_keys=True, separators=(",", ":"))


@dataclass
class MindState:
    """Replays one actor's log and rejects events that do not follow from it."""

    kinds: dict[str, str] = field(default_factory=dict)
    current: dict[str, str] = field(default_factory=dict)
    stance_tick: dict[str, int] = field(default_factory=dict)
    payloads: list[str] = field(default_factory=list)

    @property
    def head(self) -> int:
        return len(self.payloads)

    def _expect(self, item: str, allowed: tuple[str, ...], context: str) -> None:
        if self.kinds.get(item) not in allowed:
            raise ValueError(f"{context} must reference an earlier {' or '.join(allowed)}: {item}")

    def apply(self, event: dict[str, Any]) -> bool:
        """Return True when the event is new; replaying an identical logged event is a no-op."""
        seq = event["seq"]
        if seq <= self.head:
            if self.payloads[seq - 1] != payload(event):
                raise ValueError(f"event {seq} conflicts with the immutable logged event")
            return False
        if seq != self.head + 1:
            raise ValueError(f"event {seq} leaves a gap after event {self.head}")
        if self.head >= MAX_ITEMS:
            raise ValueError(f"mind log is limited to {MAX_ITEMS} items")
        item, op = event["id"], event["op"]
        if item in self.kinds:
            raise ValueError(f"item {item} already exists")
        if op == "concept":
            if item.startswith("core:") and item not in CORE_CONCEPTS:
                raise ValueError(f"unknown core concept {item}")
        elif op == "evidence":
            for role, target in event["involves"].items():
                self._expect(target, ("concept",), f"evidence {item} role {role}")
        elif op == "claim":
            predicate = event["predicate"]
            self._expect(predicate, ("concept",), f"claim {item} predicate")
            for role, target in event["roles"].items():
                if type(target) is not int:
                    self._expect(target, ("concept", "claim"), f"claim {item} role {role}")
            for role, kind in CORE_ROLES.get(predicate, {}).items():
                if self.kinds.get(event["roles"].get(role)) != kind:
                    raise ValueError(f"{predicate} claim {item} requires role {role} to be a {kind}")
        else:
            claim = event["claim"]
            self._expect(claim, ("claim",), f"stance {item} claim")
            for cite in event["cites"]:
                self._expect(cite["ref"], ("evidence", "claim"), f"stance {item} citation")
                if cite["ref"] == claim:
                    raise ValueError(f"stance {item} cites its own claim")
            prior = self.current.get(claim)
            if event["revises"] != prior:
                raise ValueError(
                    f"stance {item} must revise current stance {prior}" if prior
                    else f"stance {item} has no earlier stance to revise"
                )
            if prior is not None and event["tick"] < self.stance_tick[prior]:
                raise ValueError(f"stance {item} predates the stance it revises")
            self.current[claim] = item
            self.stance_tick[item] = event["tick"]
        self.kinds[item] = op
        self.payloads.append(payload(event))
        return True


@dataclass(frozen=True)
class MindLog:
    run: str
    actor: int
    events: tuple[dict[str, Any], ...]

    @classmethod
    def parse(cls, value: Any) -> MindLog:
        if not isinstance(value, dict):
            raise ValueError("mind log must be an object")
        run = identifier(value.get("run"), "run")
        actor = value.get("actor")
        if type(actor) is not int or not 0 <= actor <= 0xFFFFFFFF:
            raise ValueError("actor must be a u32 ID")
        raw = value.get("events")
        if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_BATCH:
            raise ValueError(f"events must be an array of 1–{MAX_BATCH} items")
        events = tuple(parse_event(item) for item in raw)
        if any(b["seq"] != a["seq"] + 1 for a, b in zip(events, events[1:])):
            raise ValueError("event seq values must be consecutive within a batch")
        return cls(run, actor, events)


def replay(*logs: MindLog) -> MindState:
    state = MindState()
    for log in logs:
        for event in log.events:
            state.apply(event)
    return state
