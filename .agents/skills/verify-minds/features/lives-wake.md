# A woken resident of the seeded island knows its past and its people

Since 2026-11-10 ([seeded lives](../../../../docs/SEEDED_LIVES.md)). The island's residents have authored sheets. A player speaking to one wakes it (town life layer 2), and the running `living-mind` installs its sheet without a model call (formative memories, `FEELS`, `JUDGES`, places; the secret in its own prompts only) into a scratch Neo4j, then thinks and talks for it.

## Sub-features

- Woken by the player's speech (`woken.why = speech`).
- Its `relation` rows existed before waking and cover its sheet's relations.
- Its persona is its authored narrative.
- Its first prompt names people from its sheet and recalls its authored memories (`[before all this]`).
- Its own secret reaches its own prompts; no other resident's secret reaches them.
- Paid tier (`--real PROFILE`, only when authorized): what it says when asked about another settlement, for reading against its sheet and the world tensions.

## Driving it

```bash
R=minds-lives-$(date +%Y%m%d-%H%M%S)
V=.agents/skills/verify/scripts/verify.py
python3 "$V" launch --run "$R" --seed island
CARGO_TARGET_DIR=living/target cargo build --release -p living-mind --manifest-path living/Cargo.toml
.agents/skills/verify-minds/scripts/lives_wake.py --run "$R" \
  --who "Wat Fenner=What do you make of the Kettlebridge folk?" \
  --who "Hester Crane=What do people here say about Brackenford?"
python3 "$V" cleanup --run "$R"
```

The driver starts a scratch Neo4j container (`lives-neo4j-<run>`, image `neo4j:2026.09.0`), a local fake model (`verify-llm/scripts/fake_llm.py`) unless `--real`, and the mind with `LIVING_ONLY` set to the named residents. It stops them and removes the container in `finally`. Evidence: `.local/living/verify/<run>/lives-wake/` (first prompts, replies, rows, `checks.json`, mind log, journal copy).

## Gotchas

- Names must match the compiled seed (`living/seeds/island.json`); pick residents with a secret and a partner to make the secret checks bite (Agnes and Wat Fenner).
- The player is placed beside each resident with `place_near` (admin setup); the line goes through the player's own `human_say`.
- The paid tier spends model calls for each woken resident until the driver stops the mind (about a minute each with talk turns).
