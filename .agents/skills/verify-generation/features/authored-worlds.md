# Authored worlds

## Sub-features

- Cached household sheets compile without network access or model calls.
- Compilation output is compared semantically and byte for byte with the committed `aske-coast.json`.
- Original seed files retain their hashes.
- Authored parser tests cover ages, households, sites, parent order and sheet resolution.
- Published backgrounds preserve the resolved sheet while removing its top-level secret.

`living/tools/author_world.py:168` reads the world bible, cast and cached sheets. Lines 176 and 215 guard the drafting passes; line 244 selects the compiled output path. `living/authority/src/seed.rs:251` removes the secret and resolves relations and memories. `settle_authored` at line 1250 installs the sheet.

## How to get to it (user POV)

Author a bible and cast, draft household sheets once, then compile the cached sheets with `--compile-only`. Publish the resulting seed. The free check uses the existing `living/seeds/worlds/aske-coast/sheets/` cache.

## Driving it with generation.py

```bash
.agents/skills/verify-generation/scripts/generation.py --run generation-authored-$(date +%Y%m%d-%H%M%S) --feature authored
.agents/skills/verify-generation/scripts/generation.py --run generation-authored-full-$(date +%Y%m%d-%H%M%S)
```

The focused command captures compilation and comparison. The full command also runs parser tests and publishes both authored fixtures. Read `compile.log`, `network.json`, `authored.json`, `compile-differences.json`, `seed-tests.log`, and the authored child runs' `checks.json`.

## Gotchas

- `ROOT` is derived from the script path; there is no `LIVING_ROOT` override. The copied tree redirects the tracked output without patching product code.
- The driver blocks and records socket connections and `urllib.request.urlopen`. `network.json` must be empty.
- Omitting `--compile-only` enables paid `draft_household` calls and the second pass. Do not run that tier without authorization.
- Exact secret strings and fields are checked. A sheet can still imply private information elsewhere in its prose.
