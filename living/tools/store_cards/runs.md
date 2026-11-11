---
# DRAFT, not published. The owner has not agreed to publishing, the licence or the decision
# categories below (docs/STORE.md). store.py refuses to publish while publishing is switched off.
pretty_name: Slop Art Online runs (DRAFT)
license: mit            # DRAFT: proposed to match the MIT code repository; the owner decides
language:
- en
tags:
- agents
- llm-agents
- simulation
- game
- synthetic
- ai-generated
size_categories:
- 100K<n<1M
configs:
- config_name: instances
  data_files: "batches/*/*/instances.jsonl.gz"
- config_name: calls
  data_files: "batches/*/*/calls.jsonl.gz"
- config_name: rows
  data_files: "batches/*/*/rows.jsonl.gz"
- config_name: prompts
  data_files: "batches/*/*/prompts.jsonl.gz"
- config_name: session_calls
  data_files: "sessions/*/*/calls.jsonl.gz"
- config_name: session_rows
  data_files: "sessions/*/*/rows.jsonl.gz"
---

# Slop Art Online runs (DRAFT)

> **Draft.** Nothing here is published. This card is the proposal in `docs/STORE.md`; the owner
> decides the licence and the categories marked "owner decides" before any upload.

Evidence from [Slop Art Online](https://github.com/devteapot/slop-art-online), a persistent world
in which language-model minds and people share one set of rules. A **run** is one of:

- a **trial batch** (`batches/<machine>/<batch>/`): `trials.py` puts one character, the subject,
  in a scripted world with a real model mind and everything else on scripts and behaviour graphs.
  It runs several trials, variants and replicates in parallel and records what the mind saw, said,
  planned and did. See `docs/TRIALS.md` in the code repository.
- a **play session** (`sessions/<machine>/<name>/`): the owner playing a character among residents
  that are all model minds.
- **verification evidence** (`verify/<machine>/…`): scratch worlds driven by the verification skills.

A seed does not make inference repeatable. Replicates are separate runs and should be compared side
by side, not averaged into one.

## Files of a batch

| File | One row per | Columns |
| --- | --- | --- |
| `instances.jsonl.gz` | trial instance (`<trial>-<variant>-r<k>`) | `batch`, `instance`, and `summary`, `cast`, `state`, `models`, `mind_env` as JSON text (`summary.json` holds the probes: survival, hunger, lines said, relations, tokens…) |
| `calls.jsonl.gz` | model call in the mind's journal | `batch`, `instance`, `file`, `seq`, `actor`, `at_ms`, `purpose`, `model`, `tokens`, `latency_ms`, `error`, and `entry`: the journal line, holding the actual request messages and the reply |
| `prompts.jsonl.gz` | distinct system prompt | `batch`, `instance`, `ref` (what a call's `content_ref` names), `text` |
| `rows.jsonl.gz` | row of a recorded stream | `batch`, `instance`, `stream` (`samples`, `thoughts`, `experiences`, `chronicle`, `graphs`, `mind_rows`, `events`, `census`), `seq`, `at_ms`, `row` (JSON text) |
| `files.tar.gz` | – | everything else: the batch report, runner and mind logs, `final.json`, snapshots |
| `MANIFEST.json` | – | every source file with its status (published, held, refused) and the redactions applied, by category |

`store.py fetch batch <name> --unpack` rebuilds the `trials.py` evidence layout from these files.

## Where the text comes from

- **Model output.** `reply` and much of `thoughts`, `experiences` and `chronicle` (plans, spoken
  lines, memories) were written by models served through Mistral AI's API: `zai-glm-5-3-flash`
  (Z.ai GLM), `deepseek-v4-1-flash-1017` (DeepSeek) and, in some batches, Mistral's
  `ministral-*`. They are **AI-generated** and must not be presented as human writing.
- **Prompts** are built by the mind service from the world's rows and the project's prompt frames.
- **World rows** are written by the game's authority (SpacetimeDB module) from its rules.

## Redactions (always)

API keys and tokens of every format, JWTs (SpacetimeDB tokens), bearer headers, `.env` contents,
the owner's name and email address, home folders (`/home/<user>`, `/Users/<user>` become `~`),
private network addresses and host names. Secrets files, browser profiles, macOS metadata files,
build output and folders the machines must not touch are refused whole. See `MANIFEST.json`.

## Owner decides (before any upload)

- `model_exchanges`: publish the journals' requests and replies, or not.
- `owner_lines`: the owner's own typed lines in play sessions. Default **excluded**: each is
  replaced by `[owner line]` wherever it recurs.
- `owner_first_name`: the player character carries the owner's first name. Default **redacted** to `Player`.
- `owner_notes`: the owner's written feedback files.
- `session_media`: play-session stills and video (they show typed lines as drawn).

## Licences of what this derives from (DRAFT notes, not legal advice)

- **Model outputs.** Mistral's Commercial Terms of Service (effective 2026-09-25) give the customer
  ownership of Output (s.3.1) and forbid implying a human wrote it (s.3.2). Its Additional Product
  Terms (s.6) treat GLM and DeepSeek as third-party models whose rights stay with their licensors.
  GLM open weights are MIT (checked on the GLM-4.5 card). DeepSeek's model licence (v1.0) says it
  "claims no rights in the Output". The exact versions behind `zai-glm-5-3-flash`,
  `deepseek-v4-1-flash-1017` and `ministral-*-latest` were not checked; see `docs/STORE.md`.
- **SpacetimeDB** (BSL 1.1) and **Neo4j** (GPLv3) are software licences. The exported JSON rows
  here are data written by the game's own module and minds, not copies of either program.
- **The game's code and rules** are MIT.

## Not included

Database replicas and WAL, Neo4j stores, trial modules (`.wasm`), derived seeds, Cargo build
folders and caches. They are regenerable in minutes from the code repository, or they are
replicas of what is published here.
