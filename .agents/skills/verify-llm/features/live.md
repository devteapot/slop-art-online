# Opt-in provider access

## Sub-features

- Load real environment keys without overriding existing variables.
- Make one minimal POST for each keyed base URL in the real models file.
- Record response shape, tokens, status and latency without keys or authorization headers.

## How to get to it (user POV)

After authorizing this particular paid run, check whether each configured endpoint accepts the selected model and returns a JSON completion.

## Driving it with live_probe.py

After authorization only:

```bash
.agents/skills/verify-llm/scripts/live_probe.py --allow-live --run llm-live-$(date +%Y%m%d-%H%M%S)
```

The command uses explicit `--models`, then active `LIVING_MODELS` from the environment or non-overriding `.env`, then the repository default. It deduplicates keyed profiles by base_url and sends one request per endpoint. It sets max_tokens 64, honors JSON mode and think effort, and makes no retry. Check `live.jsonl` and `summary.json` in the named evidence directory. Accepted replies must parse to `{"ok":true}`.

## Gotchas

This tier was not run during skill creation. The default local driver cannot invoke it. `--allow-live` is a second guard, not user authorization by itself. A provider may reject a 64-token cap or spend that budget on reasoning. Preserve that failed result. This HTTP probe does not prove the Rust mind workload or model quality. Several models sharing a base URL receive only one request using the first keyed profile by name.

Both live commands use `scripts/models_config.py`. The host's `.env` selects `.local/living/models.json`, with Luna on the local proxy at `127.0.0.1:8787`. `living/configs/models.json` is the repository example and points Luna at `codex.carlid.dev`. Following the active configuration keeps this probe and the real mind on the same route.
