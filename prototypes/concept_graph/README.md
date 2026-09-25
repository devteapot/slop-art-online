# Concept graph prototype

This is a bounded experiment for replacing fixed **mental-content vocabulary** with one personal knowledge graph and belief overlay per actor. It runs beside the game and does not modify the SpacetimeDB module, the simulation kernel, participant prompts, or the 60 Hz behavior loop. The two example perspectives are invented examples, not retained game outcomes.

## Model

Each actor's base graph holds their own `Concept` identities and sourced `SEMANTIC` links. Mira can classify the thicket as a place while Tovan calls the same physical location “the eastern trail” and classifies it as a route. Their concept nodes have different keys even when the local IDs match. An actor can also represent an unresolved referent such as “the masked stranger.” No graph content is automatically copied between actors.

Each actor also has a `Perspective`. A `Claim` connects two of that actor's concepts through a relation string, polarity and confidence. The relation is data, so `owes_food_to`, `safe_for`, `controls`, or a new relation can appear without a schema migration. A claim must cite at least one actor-scoped `Evidence` reference. `REVISES` retains the earlier claim while removing it from current context. The `semantics` command reads only the selected actor's knowledge links. Neither layer establishes objective world truth.

The prototype limits each load to 256 claims with 1–8 evidence references per claim. A claim's stored payload is immutable; its current `state` may later become `superseded` when a new claim revises it.

The current implementation accepts one actor at a time. Concept, knowledge-link, claim, evidence and perspective identities include the run and actor. Queries use that actor's exact keys. This is an application-level scope for a **trusted local experiment**, not a Neo4j database permission boundary. Do not expose this database or CLI to participants. A production controller must establish the actor's ownership and source provenance before loading personal graph changes; physical facts and published knowledge still require world-authority validation.

`snapshot.py` demonstrates a one-time bridge from one actor's current `beliefs`, `knowledge`, and `relationships` in an **owner snapshot**. It reads only the selected actor's current mind, and uses their retained personal perceptions when present. Missing sources are marked unresolved; it never looks up old content in global audit history. The legacy trust map lacks individual source IDs, so its imported relationship claims are explicitly marked as provenance-incomplete. This adapter is diagnostic, not a live sync path.

The current native controller's subjective mind lives in its separate controller database, so this owner-snapshot adapter does **not** extract that live mind. A real integration would project controller-local mind revisions through the authenticated controller path, while SpacetimeDB world authority continues to validate physical knowledge publication and actions.

## Dynamic mind log (second pilot)

`mind.py` and `mind_store.py` test a more open form beside the first pilot, whose files and data are unchanged. Each actor owns an ordered, append-only log of four item types:

- A **concept** is an actor-minted handle such as “the masked stranger”. It has no fixed kind. Classification, identity and relation meaning are claims.
- **Evidence** is a perception or seed with a tick and optional `involves` roles such as `speaker` or `place`.
- A **claim** is a proposition with a predicate concept and 1–8 named roles. Roles point to concepts or earlier claims, so “Renn said the thicket is safe” is a claim whose `content` is another claim. Predicates are concepts in the actor's own graph, so `owes` can itself be classified as an `obligation`.
- A **stance** is the actor's credence (0–100) in one claim, citing evidence or other claims as support or opposition. A later stance on the same claim must revise the current one. Both stances remain, and every cited source stays attached to the claim.

Four `core:` concepts have fixed meanings that queries rely on: `core:self`, `core:instance_of`, `core:same_as` and `core:asserted` (with `speaker` and `content` roles). All other vocabulary is actor-defined.

Loading replays the stored log through the same validator before appending. Replaying identical events is a no-op, a changed payload at an existing sequence number is rejected, and a batch that leaves a gap is rejected. Logs are limited to 256 events per batch and 1,024 items per actor. Forgetting and decay are not implemented.

The open-structure queries all stay inside one actor's graph:

- `mind-near` finds claims within a number of role edges of a concept. It does not route through the actor's self or through category claims, which would otherwise connect everything. An identity claim is an ordinary bridge.
- `mind-rests-on` finds current beliefs whose every support path to evidence passes through something the given speaker, or anyone the actor believes is that speaker, said.
- `mind-reports` shows each speaker's reported statements next to the actor's current credence in their content.
- `mind-trace` shows a claim's stance history.

With `--text`, `mind-context` and `mind-near` produce one line per claim for a model prompt. After the service and environment setup under “Run locally”:

```sh
.local/tmp/concept-graph-venv/bin/python -m prototypes.concept_graph mind-load prototypes/concept_graph/examples/mira-mind.json
.local/tmp/concept-graph-venv/bin/python -m prototypes.concept_graph mind-load prototypes/concept_graph/examples/tovan-mind.json
.local/tmp/concept-graph-venv/bin/python -m prototypes.concept_graph mind-near --run mind-pilot-1 --actor 1 --concept c:masked --text
.local/tmp/concept-graph-venv/bin/python -m prototypes.concept_graph mind-load prototypes/concept_graph/examples/mira-mind-later.json
.local/tmp/concept-graph-venv/bin/python -m prototypes.concept_graph mind-near --run mind-pilot-1 --actor 1 --concept c:masked --text
.local/tmp/concept-graph-venv/bin/python -m prototypes.concept_graph mind-rests-on --run mind-pilot-1 --actor 1 --concept c:masked
.local/tmp/concept-graph-venv/bin/python -m prototypes.concept_graph mind-reports --run mind-pilot-1 --actor 1
.local/tmp/concept-graph-venv/bin/python -m prototypes.concept_graph mind-trace --run mind-pilot-1 --actor 1 --claim k:thicket-safe
```

After the later batch, Mira believes at 65% that the masked stranger is Renn, based on Tovan's report and her own sighting. Nearby claims about the stranger now reach Renn's promises, and asking what rests on the stranger's word returns the beliefs she holds only because Renn said so. Tovan's graph uses the same local ID `c:thicket` for “the eastern trail” and never appears in her results.

## Model interpretation of retained perceptions

`interpret.py` reads one actor's perception events from an owner snapshot and asks a model to extend that actor's mind log in tick windows. The model may add concepts, claims and stances. Evidence items are generated from perceptions shown to the actor, so the model can cite them but not invent them. Each batch is validated by the same `MindState` replay. A rejected reply gets one repair attempt with the error. If that also fails, the whole batch is discarded. The prompt, raw replies, errors and accepted events are journaled per batch.

```sh
set -a; . ./.env; . .local/tmp/concept-graph.env; set +a
.local/tmp/concept-graph-venv/bin/python -m prototypes.concept_graph.interpret \
  output/typesafe-shadow/trial-03/host/sim-bevy-1789600165611/snapshot.json \
  --actor 2 --run mind-interpret-2 --out output/concept-graph/interpret-2 --prompt v2 --max-claims 10 --load
```

The first comparison used Tovan (actor 2) from `output/typesafe-shadow/trial-03`, with `gpt-5.6-luna` through the Carlid OpenAI-compatible endpoint. The endpoint rejects Python's default user agent, so the script sends its own. Of his 187 perceptions, 80 changed on their channel and were shown, in six windows of six ticks. Results are in `output/concept-graph/interpret-1` and `interpret-2`, and the minds are loaded into Neo4j as runs `mind-interpret-1` and `mind-interpret-2`.

| | Prompt v1 | Prompt v2, 10-claim budget |
|---|---|---|
| Accepted claims / stances | 85 / 91 | 25 / 31 |
| Batches rejected after repair | 1 of 6 | 0 of 6 |
| Model time / output tokens | 694 s / 37,594 | 318 s / 16,591 |
| Final rendered mind | 18,237 chars | 8,642 chars |

- **v1 transcribed instead of interpreting.** It created concepts for numbers and ticks, and one claim per shelter reading and per completed wait. The batch containing Mira's speech failed twice on references to concepts it had not created, so the baseline mind never recorded what she said.
- **v2 interpreted.** Perceptions are declared already kept, integer role values are allowed, and claims are budgeted. Tovan inferred that Mira keeps building the shelter, that it is rising, and that food first declined and later recovered. He believed he heard Mira say the shelter was at six (99%) but gave that content 5%, citing his own perception that it was already at eight. Her plan to finish building got 95% because he kept seeing her build. Her plan to rest got 75% because it rested only on her word. `mind-rests-on` returns exactly those beliefs that depend only on Mira or only on Iri.
- **Remaining gaps.**
  - Quiet windows regressed to dated quantity snapshots, with one new claim per reading and no way to supersede a value.
  - Commitments were never resolved: the shelter stopped at twelve, and Iri's promise to watch the stores was never checked.
  - Multi-part speech was bundled with an ad hoc `and` predicate.
  - Whole-batch rejection can discard the most important perception in a window.

## Run locally

From the repository root:

```sh
python3 -m venv .local/tmp/concept-graph-venv
.local/tmp/concept-graph-venv/bin/pip install -r prototypes/concept_graph/requirements.txt
mkdir -p .local/tmp
python3 - <<'PY'
from pathlib import Path
import secrets
p = Path('.local/tmp/concept-graph.env')
if not p.exists():
    p.write_text('CONCEPT_GRAPH_NEO4J_PASSWORD=' + secrets.token_hex(16) + '\n')
    p.chmod(0o600)
PY
docker compose --env-file .local/tmp/concept-graph.env -f prototypes/concept_graph/compose.yml -p sao-concept-graph up -d
set -a; . .local/tmp/concept-graph.env; set +a
.local/tmp/concept-graph-venv/bin/python -m prototypes.concept_graph load-base prototypes/concept_graph/examples/base.json
.local/tmp/concept-graph-venv/bin/python -m prototypes.concept_graph load-base prototypes/concept_graph/examples/tovan-base.json
.local/tmp/concept-graph-venv/bin/python -m prototypes.concept_graph load prototypes/concept_graph/examples/mira.json
.local/tmp/concept-graph-venv/bin/python -m prototypes.concept_graph load prototypes/concept_graph/examples/tovan.json
.local/tmp/concept-graph-venv/bin/python -m prototypes.concept_graph context --run concept-pilot-3 --actor 1
.local/tmp/concept-graph-venv/bin/python -m prototypes.concept_graph related --run concept-pilot-3 --actor 1 --concept person:renn
.local/tmp/concept-graph-venv/bin/python -m prototypes.concept_graph paths --run concept-pilot-3 --actor 1 --concept place:thicket
.local/tmp/concept-graph-venv/bin/python -m prototypes.concept_graph semantics --run concept-pilot-3 --actor 1 --concept place:thicket
.local/tmp/concept-graph-venv/bin/python -m prototypes.concept_graph semantics --run concept-pilot-3 --actor 2 --concept place:thicket
.local/tmp/concept-graph-venv/bin/python -m prototypes.concept_graph trace --run concept-pilot-3 --actor 1 --claim thicket-safe-heard
```

Neo4j Browser is at `http://127.0.0.1:7475`; Bolt is bound to `127.0.0.1:7688`. The username is `neo4j`, and the password is in the ignored local env file. The example load is idempotent. The earlier `concept-pilot-1` and `concept-pilot-2` graphs remain in the local Neo4j volume as historical prototype data; these commands use the personal-graph `concept-pilot-3` run. To stop the service while retaining its dedicated volume:

```sh
docker compose --env-file .local/tmp/concept-graph.env -f prototypes/concept_graph/compose.yml -p sao-concept-graph down
```

To inspect an existing owner export without modifying the world, use `import-snapshot SNAPSHOT --run UNIQUE_RUN --actor ACTOR`. Use a fresh run label per export because this command imports a current-state snapshot, not an ordered revision stream. Never point an untrusted actor runtime at an owner export.

## What to judge next

- Can an agent use several connected claims and conflicting reports to choose a better action than with the current flat context?
- Does a model interpreter produce well-formed open-role claims and stances from real perceptions, or does meaning drift into notes and near-duplicate predicates?
- Do the open-structure queries stay useful and bounded when a mind has hundreds of claims and hub concepts?
- Does it preserve speaker attribution, uncertain interpretations and original failed outcomes?
- Can a committed learning update be projected idempotently and in order after a relay restart, without reopening forgotten or destroyed knowledge?
- Can a reactive policy read a small, deterministic, locally materialized belief predicate without querying Neo4j on the real-time path?
- What are graph size, projection lag, scoped retrieval latency and context-token cost at representative actor counts?

The prototype has **no vector index** yet. Neo4j supports vector and full-text indexes, so a separate vector service is unnecessary for this first comparison. Embedding generation, model interpretation and graph retrieval belong outside reducers. If this model earns its place, the next design step is a replayable controller-local graph-delta stream, not full owner-snapshot polling.

## Documentation checked and design implications

- [SpacetimeDB 2.1.0 Rust SDK](https://docs.rs/spacetimedb/2.1.0/spacetimedb/), [tables](https://spacetimedb.com/docs/tables/), [table performance](https://spacetimedb.com/docs/tables/performance/), [subscriptions](https://spacetimedb.com/docs/clients/subscriptions/) and [views](https://spacetimedb.com/docs/functions/views/): the repository pins 2.1.0. Keep physical accepted state and permission checks in the world authority, and subjective knowledge in the actor's controller. If a live projector is built, use narrow actor-scoped updates and indexed access. Do not export or hydrate the whole World for routine context.
- [Neo4j Docker](https://neo4j.com/docs/operations-manual/current/docker/introduction/), [Python driver transactions](https://neo4j.com/docs/python-manual/current/transactions/) and [query parameters](https://neo4j.com/docs/python-manual/current/query-simple/): the prototype uses a versioned local image, a managed transaction for each perspective and parameterized Cypher.
- [Neo4j graph model](https://neo4j.com/docs/getting-started/graph-database/) and [W3C RDF dataset semantics](https://www.w3.org/TR/rdf11-datasets/): the common structure is a Neo4j property-graph format, not shared knowledge or an RDF/OWL implementation. Actor ownership and endorsement must be explicit; separate graph storage alone does not define either.
- [Neo4j vector indexes](https://neo4j.com/docs/cypher-manual/current/indexes/semantic-indexes/vector-indexes/) and [GraphRAG retrievers](https://neo4j.com/docs/neo4j-graphrag-python/current/user_guide_rag.html): Neo4j can combine semantic retrieval with graph traversal. The pilot first tests claim semantics and privacy without embedding cost.
