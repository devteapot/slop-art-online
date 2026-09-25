"""Validate portable claim input before it reaches Neo4j."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any


ID = re.compile(r"^[A-Za-z0-9_.:-]{1,120}$")


def identifier(value: Any, name: str) -> str:
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise ValueError(f"{name} must be a 1–120 character identifier")
    return value


def text(value: Any, name: str, maximum: int = 1280) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"{name} must be nonempty and at most {maximum} characters")
    return value


def scoped(run: str, actor: int, kind: str, local_id: str) -> str:
    return f"{run}|{actor}|{kind}|{local_id}"


@dataclass(frozen=True)
class Concept:
    id: str
    kind: str
    label: str

    @classmethod
    def parse(cls, value: Any) -> Concept:
        if not isinstance(value, dict):
            raise ValueError("concept must be an object")
        return cls(
            identifier(value.get("id"), "concept.id"),
            identifier(value.get("kind"), "concept.kind"),
            text(value.get("label"), "concept.label", 240),
        )


@dataclass(frozen=True)
class SemanticLink:
    subject: str
    relation: str
    object: str
    source: str

    @classmethod
    def parse(cls, value: Any) -> SemanticLink:
        if not isinstance(value, dict):
            raise ValueError("semantic link must be an object")
        return cls(
            identifier(value.get("subject"), "link.subject"),
            identifier(value.get("relation"), "link.relation"),
            identifier(value.get("object"), "link.object"),
            identifier(value.get("source"), "link.source"),
        )


@dataclass(frozen=True)
class BaseGraph:
    run: str
    actor: int
    concepts: tuple[Concept, ...]
    links: tuple[SemanticLink, ...]

    @classmethod
    def parse(cls, value: Any) -> BaseGraph:
        if not isinstance(value, dict):
            raise ValueError("base graph must be an object")
        run = identifier(value.get("run"), "run")
        actor = value.get("actor")
        if type(actor) is not int or not 0 <= actor <= 0xFFFFFFFF:
            raise ValueError("base graph actor must be a u32 ID")
        raw_concepts = value.get("concepts")
        raw_links = value.get("links")
        if not isinstance(raw_concepts, list) or len(raw_concepts) > 256:
            raise ValueError("base concepts must be an array of at most 256 items")
        if not isinstance(raw_links, list) or len(raw_links) > 256:
            raise ValueError("base links must be an array of at most 256 items")
        concepts = tuple(Concept.parse(item) for item in raw_concepts)
        ids = {concept.id for concept in concepts}
        if len(ids) != len(concepts):
            raise ValueError("duplicate personal concept ID")
        links = tuple(SemanticLink.parse(item) for item in raw_links)
        if any(link.subject not in ids or link.object not in ids for link in links):
            raise ValueError("knowledge link endpoint missing from personal concepts")
        if len(set(links)) != len(links):
            raise ValueError("duplicate semantic link")
        return cls(run, actor, concepts, links)


@dataclass(frozen=True)
class Evidence:
    id: str
    kind: str
    summary: str

    @classmethod
    def parse(cls, value: Any) -> Evidence:
        if not isinstance(value, dict):
            raise ValueError("evidence must be an object")
        return cls(
            identifier(value.get("id"), "evidence.id"),
            identifier(value.get("kind"), "evidence.kind"),
            text(value.get("summary"), "evidence.summary"),
        )


@dataclass(frozen=True)
class Claim:
    id: str
    subject: Concept
    relation: str
    object: Concept
    confidence: int
    polarity: str
    state: str
    evidence: tuple[Evidence, ...]
    supersedes: str | None = None
    note: str = ""

    @classmethod
    def parse(cls, value: Any) -> Claim:
        if not isinstance(value, dict):
            raise ValueError("claim must be an object")
        confidence = value.get("confidence")
        if type(confidence) is not int or not 0 <= confidence <= 100:
            raise ValueError("claim.confidence must be an integer from 0 to 100")
        polarity = value.get("polarity", "positive")
        state = value.get("state", "active")
        if polarity not in ("positive", "negative", "uncertain"):
            raise ValueError("claim.polarity must be positive, negative or uncertain")
        if state not in ("active", "superseded", "retracted"):
            raise ValueError("claim.state is invalid")
        evidence = value.get("evidence")
        if not isinstance(evidence, list) or not 1 <= len(evidence) <= 8:
            raise ValueError("claim requires 1–8 owned evidence references")
        sources = tuple(Evidence.parse(item) for item in evidence)
        if len({source.id for source in sources}) != len(sources):
            raise ValueError("duplicate evidence IDs in claim")
        supersedes = value.get("supersedes")
        if supersedes is not None:
            supersedes = identifier(supersedes, "claim.supersedes")
        note = value.get("note", "")
        if not isinstance(note, str) or len(note) > 1280:
            raise ValueError("claim.note must be at most 1280 characters")
        return cls(
            identifier(value.get("id"), "claim.id"),
            Concept.parse(value.get("subject")),
            identifier(value.get("relation"), "claim.relation"),
            Concept.parse(value.get("object")),
            confidence,
            polarity,
            state,
            sources,
            supersedes,
            note,
        )

    def payload(self) -> str:
        from dataclasses import asdict

        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class Perspective:
    run: str
    actor: int
    claims: tuple[Claim, ...]

    @classmethod
    def parse(cls, value: Any) -> Perspective:
        if not isinstance(value, dict):
            raise ValueError("perspective must be an object")
        run = identifier(value.get("run"), "run")
        actor = value.get("actor")
        if type(actor) is not int or not 0 <= actor <= 0xFFFFFFFF:
            raise ValueError("actor must be a u32 ID")
        raw = value.get("claims")
        if not isinstance(raw, list) or len(raw) > 256:
            raise ValueError("claims must be an array of at most 256 items")
        claims = tuple(Claim.parse(item) for item in raw)
        ids = {claim.id for claim in claims}
        if len(ids) != len(claims):
            raise ValueError("duplicate claim IDs")
        for claim in claims:
            if claim.supersedes is not None and claim.supersedes == claim.id:
                raise ValueError("claim cannot supersede itself")
        return cls(run, actor, claims)
