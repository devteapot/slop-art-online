# Attention cues through a mind

What a mind writes should bring it to think (docs/ATTENTION.md), from the reply to the thought it asks for.

## What it does (user POV)

- **The prompt** (with the world's `cues_on` law; `prompts.rs` `notice_field`, `cue_line`): the think and consolidate replies gain an optional `notice` list (`for`: a stance key, `project:<key>` or `goal:<its words>`; `who`, `doing`, `thing`, `at`, `within`, `near_me`, `why`). Its examples are placeholders, naming no one and no duty (test `cue_examples_name_no_one`). The think prompt gains `# What you watch for`: each cue, how often it made the person think, or why the world does not watch for it. With the law off neither appears and a reply's `notice` is not kept (`memory::without_notice`).
- **Memory** (`memory.rs` `sugar_into`, `cue_for`, `cue_entry`): cues are kept on the concept they serve as its `notice` property, replacing that concept's earlier cues (a `for` alone clears them). The compile step keeps the think decision's `notice` (`keep`, with thought, say, judgments and places).
- **Projection** (`Store::projection`, `Minds::project`): a stance's cues while the stance is held, a project's while it is pursued, a goal's while the persona still has that goal (`same_goal`); newest 8, sent as `MindUpdate.cues` (the complete set). Without a store no cues are projected.
- **The fire** (authority, verify-core [cues.md](../../verify-core/features/cues.md)): a `noticed` experience quoting the `why`, and a request to think whose reason is that line; the rethink gate passes it (`rethink.json` `urgent`).
- **Player memory** keeps no cues (`lived.rs`).

## Driving it

`scripts/cues_mind.py` (about 3 minutes; Neo4j as `privacy.py`):

```bash
export LIVING_STDB_CONTAINER=slop-trials-stdb LIVING_STDB_URL=http://127.0.0.1:3320 \
  LIVING_PRIVACY_NEO4J=slop-trials-neo4j:bolt://127.0.0.1:7699 LIVING_PRIVACY_NEO4J_ENV=<file with LIVING_NEO4J_PASSWORD=>
python3 .agents/skills/verify-minds/scripts/cues_mind.py --run minds-cues-$(date +%Y%m%d-%H%M%S)
```

It sets `cues_on`, starts the real mind for one resident W against the fake model, and asks W to think (`Run.request`). The fake think reply writes a stance and a cue on it (`who: unknown, near_me: 10`, a `why` with a unique word). Checks: the `cue` row arrives through `mind_update`, watched, in those words; a player W does not know placed 3 m away gives one `noticed` row quoting the `why`; the next journaled think request carries that line; the think prompts offer `notice` and `# What you watch for`, which lists the cue as having made W think; `fires` counts it. Evidence: `cues.json`, `journal/`, `fake-requests.jsonl`, `mind.log`. Its Neo4j nodes are deleted at the end (`neo4j-cleanup-check.txt`).
