# Client protocol verification map

| Feature | File | Evidence |
| --- | --- | --- |
| Ad-hoc query for client triage, initial rows and live changes | [triage.md](triage.md) | `adhoc-suite.jsonl`, query-specific `.jsonl` |
| Anonymous observer and inspected-character subscriptions | [subscriptions.md](subscriptions.md) | `anonymous-base.json`, `inspected-character.json` |
| Private-table refusals and known public-perception leaks | [visibility.md](visibility.md) | `visibility.json`, `privacy-*.json` |
| Identity-scoped `my_deliberations` view | [deliberations.md](deliberations.md) | `view-*.json` |
| Reducer permissions and allowed effects for each identity | [permissions.md](permissions.md) | `reducers.md`, `reducers.json`, `reducer-effects.json` |
| Dropped WebSocket connection and resubscription | [reconnect.md](reconnect.md) | `reconnect.json` |

Run every feature with the automatic recipe in [SKILL.md](../SKILL.md). The baseline is a fresh `verify-client-*` database launched and checked by the shared harness. The fixed suite requires the primary player to be named `ClientPrimary`. Other identities and fixtures stay within that database.
