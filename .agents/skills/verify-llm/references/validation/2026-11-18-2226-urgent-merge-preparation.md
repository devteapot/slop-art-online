# Preparing a prompt without holding a model slot

Run `llm-urgent-ab-verify` drove the release mind on a private SpacetimeDB 2.14.1 server from base `04b9ccc2`. All replies came from loopback fake providers.

- The fake-provider contract passed all ten scenarios.
- The LLM unit suite passed 33 tests with one ignored. A nominated deliberation held its queue ticket while an ordinary request used the only transport slot. The prepared deliberation dispatched on its original lane and an abandoned preparation released its ticket.
- `basic`, `overflow`, `outage`, `deliberation-retry`, `fast-route` and `fast-cap` all passed. The existing retry, pending-request recovery and separate fast-slot behavior were exercised.
- The fixed-site comparison counts starts at fake-provider receipt for both arms. The A/B timing and the grant-to-dispatch hold are recorded in [Mind harness §8](../../../../../docs/MIND_HARNESS.md#fixed-site-follow-up-2026-11-18).

Evidence includes the suite's `results.json`, unit-test log, fake contract run and per-case journals. The private-server evidence archive is `~/slop-evidence/urgent-merge-ab-20261118.tar.zst`.
