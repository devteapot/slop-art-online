# Client protocol verification map

| Feature | File | Evidence |
| --- | --- | --- |
| Ad-hoc query for client triage, initial rows and live changes | [triage.md](triage.md) | `adhoc-suite.jsonl`, query-specific `.jsonl` |
| Combat: private combat tables, the `my_combat` and `my_skill_uses` views, public `skill_card` (and `fighter` in an open build) | [combat.md](combat.md) | `combat-*.json`, `visibility.json`, `reducers.json` |
| Dropped WebSocket connection and resubscription | [reconnect.md](reconnect.md) | `reconnect.json` |
| Game client on a land world: the perception views and chunk windows of world data, regenerated land, join, what it shows of others (labels, bands, appraised health, dress, indoors), speech, death and rejoin | [game-client.md](game-client.md) | game `game.log`, photographs, probe `.jsonl`, metric samples |
| Identity-scoped `my_deliberations` view | [deliberations.md](deliberations.md) | `view-*.json` |
| Perception: `seen_*` views in sight, beyond sight and behind a wall; `seen_characters` as the `perceived_of` projection (someone too far away to make out: `far_label.py`); `my_*` own-state views; `my_offers` (an offer reaches its maker as outgoing and its addressee as incoming, no one else); `my_senses` (one row, the caller's own); `my_act_outcomes` (only the caller's character's rows) | [perception.md](perception.md) | `sight.json`, `sight-*.json`, `seen-characters.json`, `own-*.json`, `offers.json`, `offers-*.json` |
| Presence: connections counted, a takeover after `takeover_s` with no connection, the handback on a new connection; presence private | [presence.md](presence.md) | `presence.json`, `presence-*.json` |
| Private-table refusals (anonymous and player), and the open (diagnostic) build's public tables; speech: `heard` private, `my_heard` scoped to the speaker, `speech_card` public | [visibility.md](visibility.md) | `visibility.json`, `privacy-*.json`, `open-build-tables.json`, `own-*.json`, `speech-card-public.json` |
| Reducer permissions and allowed effects for each identity | [permissions.md](permissions.md) | `reducers.md`, `reducers.json`, `reducer-effects.json` |
| The field of view (the `fov_on` law, `set_world_law` by the admin): facing away the other is not in my perceived set and comes as a `heard_sounds` row with no id; facing it, seen; at the field's edge kept by the margin, not taken afresh; off again all round. `heard`, `hear_salt`, `law_change` private; `set_world_law` admin only | [perception.md](perception.md#the-field-of-view) | `field.json`, `field-*.json`, `visibility.json`, `reducers.json` |
| The observer's owner subscriptions and inspected-character queries | [subscriptions.md](subscriptions.md) | `observer-base.json`, `anonymous-base.json`, `inspected-character.json` |
| Tile classes a client receives in `terrain_chunk` on a land world (drops 8, low 9) equal the rules' own count of the hosted land | [game-client.md](game-client.md#tile-classes) | `terrain-all.jsonl`, `terrain-all-classes.json` |
| Town life: public `act_card` and `weather` (and `doing` in an open build); admin-only `set_weather` | [town.md](town.md) | `town-public.json`, `reducers.json` |

Run every feature except `game-client` with the automatic recipe in [SKILL.md](../SKILL.md), once per build (the default `scoped` and `LIVING_PERCEPTION=open`; docs/PERCEPTION.md). `game-client` runs the real game client headless against a land world (`--seed island`), as its file describes. The baseline is a fresh `verify-client-*` database launched and checked by the shared harness. The fixed suite requires the primary player to be named `ClientPrimary`. Other identities and fixtures stay within that database.
