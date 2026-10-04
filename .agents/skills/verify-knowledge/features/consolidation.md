# Real consolidation and projections

## Sub-features

- The real mind subscribes to `verify-knowledge-*` and connects to its scratch Neo4j.
- A local scripted consolidation adds a `KNOWS` fact, an arbitrary `SAFE_AT` relation, feelings, a judgment, a place and a kept memory anchored to an actual experience ID.
- Saved Cypher shows concepts, memories, identity history and every fixed edge type. `SAFE_AT` is stored as `RELATES`. Fixture ideas carry structural `CHILD_OF` and `PARENT_OF` links. Renaming an existing authored stance retains `MERGED_INTO` history.
- `relation`, `judgment`, `place` and `belief` receive the patch through the mind's `mind_update` call.
- `persona` receives Oren's authored identity. The scripted reply leaves `identity` null and preserves it.
- A consolidation thought records the accepted reply and patch. The fake request log and copied production journal retain the exact exchange.

Sources: `living/mind/src/mind.rs:1516`, `mind.rs:825`, `mind.rs:673`; `living/mind/src/memory.rs:533`; `living/authority/src/tables.rs:521`.

## How to get to it (user POV)

A character hears and experiences events, integrates them into its personal graph and uses the projected relations and judgments in its behavior. An observer can inspect the projected rows. The local fake only replaces the external model boundary.

## Driving it with verify_knowledge.py

```bash
.agents/skills/verify-knowledge/scripts/verify_knowledge.py run --run knowledge-consolidation-$(date +%Y%m%d-%H%M%S)
```

The helper launches with `--seed authored-test`, controls only Oren with `LIVING_ONLY`, introduces four speech experiences through the shared player identity and invokes the shared fake directly. Inspect `memory-input.json`, `fake-script.json`, `models.json`, `requests.jsonl`, `mind.log`, `graph-nodes.*`, `graph-edges.*`, `projection-*.json`, `consolidation-thought.json` and `journal/`.

## Gotchas

- Consolidation has salience, batch and minimum-gap rules. The runner waits for projected effects rather than trusting a received fake request.
- A fake patch is fixture content. It proves plumbing and projection, not authentic model learning or epistemic truth.
- Persona in this scene comes from the authored sheet, not a consolidation-driven identity revision. Identity revision itself runs in the ignored graph tests.
- Merges operate on concepts that already exist before the patch's node additions. The fixture merges `stance:strangers_are_trouble` into `stance:outsiders_are_trouble`.
- Explicit environment variables override local `.env` files. Every configured model URL is loopback and every key is a local dummy.
