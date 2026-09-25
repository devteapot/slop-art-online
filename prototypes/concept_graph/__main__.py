"""CLI for the Neo4j concept-graph prototype."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .mind import MindLog
from .mind_store import MindStore, render
from .model import BaseGraph, Perspective, identifier
from .snapshot import current_mind
from .store import GraphStore


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    load = commands.add_parser("load", help="Load one actor-scoped claim file")
    load.add_argument("file", type=Path)
    load_base = commands.add_parser("load-base", help="Load one actor's concepts and knowledge links")
    load_base.add_argument("file", type=Path)
    imported = commands.add_parser("import-snapshot", help="Import one actor's current mind from an owner snapshot")
    imported.add_argument("file", type=Path)
    imported.add_argument("--run", required=True)
    imported.add_argument("--actor", required=True, type=int)
    for name in ("context", "related", "paths", "semantics", "trace"):
        command = commands.add_parser(name)
        command.add_argument("--run", required=True)
        command.add_argument("--actor", required=True, type=int)
        if name in ("related", "paths", "semantics"):
            command.add_argument("--concept", required=True)
        if name == "trace":
            command.add_argument("--claim", required=True)
    mind_load = commands.add_parser("mind-load", help="Append one batch of an actor's mind log")
    mind_load.add_argument("file", type=Path)
    for name in ("mind-context", "mind-near", "mind-rests-on", "mind-reports", "mind-trace"):
        command = commands.add_parser(name)
        command.add_argument("--run", required=True)
        command.add_argument("--actor", required=True, type=int)
        if name in ("mind-context", "mind-near"):
            command.add_argument("--text", action="store_true", help="Render one line per claim")
        if name == "mind-near":
            command.add_argument("--concept", required=True)
            command.add_argument("--depth", type=int, default=3)
        if name == "mind-rests-on":
            command.add_argument("--concept", required=True)
        if name == "mind-reports":
            command.add_argument("--speaker")
        if name == "mind-trace":
            command.add_argument("--claim", required=True)
    args = parser.parse_args()

    if args.command == "mind-load":
        log = MindLog.parse(json.loads(args.file.read_text()))
    elif args.command.startswith("mind-"):
        identifier(args.run, "run")
        if not 0 <= args.actor <= 0xFFFFFFFF:
            parser.error("actor must be a u32 ID")
        for name in ("concept", "speaker", "claim"):
            if getattr(args, name, None) is not None:
                identifier(getattr(args, name), name)
    elif args.command == "load":
        perspective = Perspective.parse(json.loads(args.file.read_text()))
    elif args.command == "load-base":
        base = BaseGraph.parse(json.loads(args.file.read_text()))
    elif args.command == "import-snapshot":
        perspective = current_mind(
            json.loads(args.file.read_text()), identifier(args.run, "run"), args.actor
        )
    else:
        identifier(args.run, "run")
        if not 0 <= args.actor <= 0xFFFFFFFF:
            parser.error("actor must be a u32 ID")
        if args.command in ("related", "paths", "semantics"):
            identifier(args.concept, "concept")
        if args.command == "trace":
            identifier(args.claim, "claim")

    password = os.environ.get("CONCEPT_GRAPH_NEO4J_PASSWORD")
    if not password:
        parser.error("set CONCEPT_GRAPH_NEO4J_PASSWORD")
    try:
        from neo4j import GraphDatabase
    except ImportError as error:
        parser.error(f"install requirements.txt in a virtual environment: {error}")
    uri = os.environ.get("CONCEPT_GRAPH_NEO4J_URI", "bolt://127.0.0.1:7688")
    database = os.environ.get("CONCEPT_GRAPH_NEO4J_DATABASE", "neo4j")
    with GraphDatabase.driver(uri, auth=("neo4j", password)) as driver:
        driver.verify_connectivity()
        if args.command.startswith("mind-"):
            minds = MindStore(driver, database)
            if args.command == "mind-load":
                minds.initialize()
                result = minds.load(log)
            elif args.command == "mind-context":
                result = minds.context(args.run, args.actor)
            elif args.command == "mind-near":
                result = minds.near(args.run, args.actor, args.concept, args.depth)
            elif args.command == "mind-rests-on":
                result = minds.rests_on(args.run, args.actor, args.concept)
            elif args.command == "mind-reports":
                result = minds.reports(args.run, args.actor, args.speaker)
            else:
                result = minds.trace(args.run, args.actor, args.claim)
            if getattr(args, "text", False):
                print(render(result))
            else:
                print(json.dumps(result, indent=2, sort_keys=True))
            return
        store = GraphStore(driver, database)
        if args.command in ("load", "import-snapshot", "load-base"):
            store.initialize()
            if args.command == "load-base":
                store.load_base(base)
                result = {"run": base.run, "actor": base.actor,
                          "concepts": len(base.concepts), "links": len(base.links)}
            else:
                store.load(perspective)
                result = {"run": perspective.run, "actor": perspective.actor, "claims": len(perspective.claims)}
        elif args.command == "context":
            result = store.context(args.run, args.actor)
        elif args.command == "related":
            result = store.related(args.run, args.actor, args.concept)
        elif args.command == "paths":
            result = store.paths(args.run, args.actor, args.concept)
        elif args.command == "semantics":
            result = store.semantics(args.run, args.actor, args.concept)
        else:
            result = store.trace(args.run, args.actor, args.claim)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
