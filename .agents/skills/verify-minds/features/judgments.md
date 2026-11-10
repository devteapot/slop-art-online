# Judgments refreshed in the background (Jev; `LIVING_JEV=1`)

A graph condition `{"judged": {"q": "fight_risk", "above": 0.6, "else": false}}` reads a cached typed judgment in the authority's tick and never waits: with no fresh one (none yet, expired or failed) it is its `else`. The mind service keeps the cache fresh off the real-time path: for each character it thinks for whose graph reads a declared question and which fought in the last 20 s, it asks the due questions (`refresh_s`) in one `POST /v1/systemone` (TypeSafe's Jev) with only the character's own state, then calls `mind_judged` (upsert by question, `ttl_s`). Declarations: `living/configs/judgments.json` (`LIVING_JUDGMENTS`). Design: docs/MIND_HARNESS.md, item 4.

## Sub-features

- The request's `state` is the character's goals, plan and temperament, its body as last felt in a deliberation scene (with its age), its last ten experiences and its feelings about who is in them.
- Every exchange is journaled with purpose `judge`, latency, `prompt_tokens` (input tokens), `cost_usd` and the cached values.
- `mind_judged` accepts only the character's controller; at most 8 judgments per character; a TTL of at most ten minutes; the rows die with the character.

Sources: `living/mind/src/mind/judge.rs`, `living/configs/judgments.json`, `living/authority/src/mind.rs` (`mind_judged`), `living/authority/src/tables.rs` (`judged`), `living/authority/src/brain.rs` (`Cond::Judged`), `living/rules/src/graph.rs` (`Judged`).

## Driving it

```bash
.agents/skills/verify-minds/scripts/verify_minds.py --run minds-$(date +%Y%m%d-%H%M%S) --case jev
```

A defender with a desires graph whose first branch flees while `fight_risk` is above 0.6 is struck by another adult. The fake Jev answers 0.9; the case waits for the `judged` row (0.9, an expiry after its update), for the defender's activity to become a flee, and checks the request's state and the journal. `living/tools/judged_fight.py` compares arms without Jev, with the fake and with the real Jev.

## Gotchas

- The defender's graph is a `desires` top level: a reply that keeps the current graph would otherwise have `keep_needs` rebuild a flat graph around the body's needs.
- The body in the state is read from the `vitals` the service subscribes to (its own characters, since feedback-1), at the moment of the request, with `felt` in words; the last deliberation scene's body is the fallback when no row has arrived.
