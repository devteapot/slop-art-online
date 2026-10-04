# Basic exchange and journal

## Sub-features

- POST and valid replies for think, deliberate, consolidate and talk.
- Output cap, JSON mode, effort map, token accounting and all ten journal fields.
- A current-plan routine, installed mind brain, thoughts and speech.

## How to get to it (user POV)

Start the mind service with a keyed OpenAI-compatible profile. A person thinks, installs a plan, remembers experiences and answers another person.

## Driving it with verify_llm.py

```bash
.agents/skills/verify-llm/scripts/verify_llm.py --run llm-$(date +%Y%m%d-%H%M%S) --case basic
```

`primary-requests.jsonl`, `journal/`, `thoughts.json`, `brain-after.json`, `routines-after.json`, `speech-after.json` and `talk-speech.json` prove the result. All four purposes must appear. Successful tokens must be 17. The requests must carry max_tokens 256 and JSON object mode.

## Gotchas

`living/mind/src/llm.rs:336-391` builds and journals requests. `mind.rs:1220-1389` compiles plans. `mind/talk.rs:486-505` parses conversation output. A bootstrap identity also uses consolidate, so check the integrated-experiences log for actual consolidation. Speech is taken from think, even if the compiler offers different words. The seeded world has many people, but only one receives model calls.
