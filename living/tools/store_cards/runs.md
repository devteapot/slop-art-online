---
pretty_name: Slop Art Online runs
license: mit
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
# Explicit column types: a column that is null throughout one file (error, at_ms) would
# otherwise be typed null from the first file and fail to cast the next.
dataset_info:
- config_name: instances
  features:
  - name: batch
    dtype: string
  - name: instance
    dtype: string
  - name: summary
    dtype: string
  - name: cast
    dtype: string
  - name: state
    dtype: string
  - name: models
    dtype: string
  - name: mind_env
    dtype: string
- config_name: calls
  features:
  - name: batch
    dtype: string
  - name: instance
    dtype: string
  - name: file
    dtype: string
  - name: seq
    dtype: int64
  - name: actor
    dtype: string
  - name: at_ms
    dtype: int64
  - name: purpose
    dtype: string
  - name: model
    dtype: string
  - name: tokens
    dtype: int64
  - name: latency_ms
    dtype: int64
  - name: error
    dtype: string
  - name: entry
    dtype: string
- config_name: rows
  features:
  - name: batch
    dtype: string
  - name: instance
    dtype: string
  - name: stream
    dtype: string
  - name: seq
    dtype: int64
  - name: at_ms
    dtype: int64
  - name: row
    dtype: string
- config_name: prompts
  features:
  - name: batch
    dtype: string
  - name: instance
    dtype: string
  - name: ref
    dtype: string
  - name: text
    dtype: string
configs:
- config_name: instances
  data_files: "batches/*/*/instances.jsonl.gz"
- config_name: calls
  data_files: "batches/*/*/calls.jsonl.gz"
- config_name: rows
  data_files: "batches/*/*/rows.jsonl.gz"
- config_name: prompts
  data_files: "batches/*/*/prompts.jsonl.gz"
---

# Slop Art Online runs

Records from a **research build** of [Slop Art Online](https://github.com/devteapot/slop-art-online),
a persistent world in which language-model minds and people share one set of rules. This is
not a finished game: the rules, prompts and models changed from batch to batch, and many
batches were run to find faults.

**Much of the text here is AI-generated.** Model replies, and the thoughts, plans, memories and
spoken lines in the world rows, were written by language models (see "Models"). They must not be
presented as human writing.

## What a run is

A **trial batch** (`batches/<machine>/<batch>/`) is one run of `living/tools/trials.py`. Each trial
puts one character, the subject, in a scripted world with a real model mind, while everything else
follows scripts and behaviour graphs. A batch runs several trials, mind variants and replicates in
parallel, and records what the mind perceived, said, planned and did. `docs/TRIALS.md` in the code
repository describes the format.

A **play session** (`sessions/<machine>/<name>/`) is a run in which a person played one character
among residents that are all model minds.
- **The person's typed lines are removed:** each is replaced by `[owner line]`, and model replies,
  rows and lines that quote or repeat one are dropped.
- **Their character is called "Player".**
- **Kept:** what that character did in the world (where it went, what it did, who it fought) is part
  of the record.
- **Published:** only the record of the run (the minds' journals, the run's logs, the scene's rules and
  description). The person's feedback, screenshots and video, and any analysis of their play, are
  not published.

A seed does not make inference repeatable. Replicates are separate runs: compare them side by
side rather than averaging them into one.

## Files of a batch

| File | One row per | Columns |
| --- | --- | --- |
| `instances.jsonl.gz` | trial instance (`<trial>-<variant>-r<k>`) | `batch`, `instance`, and as JSON text: `summary` (the probes: survival, hunger, lines said, relations, tokens…), `cast`, `state`, `models`, `mind_env` |
| `calls.jsonl.gz` | model call in the mind's journal | `batch`, `instance`, `file`, `seq`, `actor`, `at_ms`, `purpose`, `model`, `tokens`, `latency_ms`, `error`, and `entry`: the journal line with the actual request messages and the reply |
| `prompts.jsonl.gz` | distinct system prompt | `batch`, `instance`, `ref` (what a call's `content_ref` names), `text` |
| `rows.jsonl.gz` | row of a recorded stream | `batch`, `instance`, `stream` (`samples`, `thoughts`, `experiences`, `chronicle`, `graphs`, `mind_rows`, `events`, `census`), `seq`, `at_ms`, `row` (JSON text) |
| `files.tar.gz` | – | everything else: the batch report, runner and mind logs, `final.json`, snapshots |
| `MANIFEST.json` | – | every source file with its status and the redactions applied by category; the models used; the tool's commit |

`python3 living/tools/store.py fetch batch <name> --unpack` (in the code repository) rebuilds the
`trials.py` evidence layout from these files.

## Reproducing a run

1. Read the batch's `batch.json` in `files.tar.gz`: `commit` is the code it ran on (`dirty: true`
   means local changes on top of it), plus `trials`, `variants`, `replicates`, `minutes`, `fake`,
   `parallel` and `sample_s`.
2. Check out that commit of the code repository.
3. Run `python3 living/tools/trials.py up`, then `trials.py build <trials…>`, then
   `trials.py run --batch <new name> <trials…> --variants <…> --replicates <n>`, with the same
   arguments.
4. Real variants call models through Mistral AI's API and need your own key. `--fake` answers
   them from the verification fake server instead.

The same commit and arguments give the same world and script. The model's replies will differ.

## Models

| Model id in the journals | Served by | Weights and licence | Status |
| --- | --- | --- | --- |
| `zai-glm-5-3-flash` | Mistral AI API | Z.ai [GLM-5.3-Flash](https://huggingface.co/zai-org/GLM-5.3-Flash), MIT (the API id is matched to the weights by name) | verified 2026-11-11 |
| `deepseek-v4-1-flash-1017` | Mistral AI API | [DeepSeek-V4.1-Flash-1017](https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash-1017), MIT | verified 2026-11-11 |
| `fake-*` | the verification fake server | no model | – |
| `ministral-*-latest` | Mistral AI API | which release `-latest` serves was not established | **UNVERIFIED**: batches with these calls are not published |
| `mistral-small-latest` | Mistral AI API | release and licence behind the alias not read | **UNVERIFIED**: not published |
| `gpt-6-luna` | a private endpoint | provider terms not read | **UNVERIFIED**: not published |

Mistral AI's [Commercial Terms of Service](https://legal.mistral.ai/terms/commercial-terms-of-service)
(effective 2026-09-25) give the customer ownership of Output (s.3.1) and forbid implying that a
human generated it (s.3.2). Its [Additional Product Terms](https://legal.mistral.ai/terms/additional-terms)
(s.6) leave the rights in third-party models with their licensors.

## What was removed

- **Always:**
  - API keys and tokens of every format, JWTs (SpacetimeDB tokens) and bearer headers;
  - `.env` contents;
  - the owner's name and email address;
  - home folders (`/home/<user>` and `/Users/<user>` become `~`);
  - private network addresses and host names.
- **Refused whole:** secrets files, browser profiles, macOS metadata files, build output, and
  folders the machines must not touch.
- **Per file:** `MANIFEST.json` lists every file and its redactions.

The world's own content (names of residents, places, the rules) is fiction and is kept.

## Licence

MIT, like the code. The game's code and rules are MIT. Model outputs are covered by the terms
above. The exported rows are data written by the game's own SpacetimeDB module and its mind
service; they are not copies of SpacetimeDB (BSL 1.1) or Neo4j (GPLv3).

## Not included

Not included, because they are regenerable in minutes from the code repository or are replicas of
what is published here:
- database replicas and WAL;
- Neo4j stores;
- trial modules (`.wasm`) and derived seeds;
- Cargo build folders and caches.
