# Client protocol verification map

| Feature | File | Evidence |
| --- | --- | --- |
| Ad-hoc query for client triage, initial rows and live changes | [triage.md](triage.md) | `adhoc-suite.jsonl`, query-specific `.jsonl` |
| Anonymous observer and inspected-character subscriptions | [subscriptions.md](subscriptions.md) | `anonymous-base.json`, `inspected-character.json` |
| Private-table refusals and known public-perception leaks | [visibility.md](visibility.md) | `visibility.json`, `privacy-*.json` |
| Identity-scoped `my_deliberations` view | [deliberations.md](deliberations.md) | `view-*.json` |
| Reducer permissions and allowed effects for each identity | [permissions.md](permissions.md) | `reducers.md`, `reducers.json`, `reducer-effects.json` |
| Combat: private combat tables, the `my_combat` and `my_skill_uses` views, public `fighter` and `skill_card` | [combat.md](combat.md) | `combat-*.json`, `visibility.json`, `reducers.json` |
| Dropped WebSocket connection and resubscription | [reconnect.md](reconnect.md) | `reconnect.json` |
| Game client on a land world: staged subscriptions, chunk windows, regenerated land, join, speech, death and rejoin | [game-client.md](game-client.md) | game `game.log`, photographs, probe `.jsonl`, metric samples |

Run every feature except `game-client` with the automatic recipe in [SKILL.md](../SKILL.md). `game-client` runs the real game client headless against a land world (`--seed island`), as its file describes. The baseline is a fresh `verify-client-*` database launched and checked by the shared harness. The fixed suite requires the primary player to be named `ClientPrimary`. Other identities and fixtures stay within that database.
