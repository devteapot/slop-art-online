# Heed for players: counts by kind and the centre, as a client receives them (branch `heed-player-2`)

Follows 2026-11-26-1942-heed-player-2.md. Branch `heed-player-2` with `origin/heed-client` (`d1f7d279a`) merged; module at `b666b4780`, bindings at `08e860530` (regenerated with the pinned image; the probe rebuilt on them). Private `hp-stdb` (SpacetimeDB 2.14.1). Shape change: `seen_throng`'s `people`, `wolves`, `deer`, `others`, `centre_x`, `centre_y`. Map: features/perception.md "Heed for players", the README row (merged with the heed-client branch's row: the game client subscribes `seen_throng` only while both laws are on).

| Run | Driven | Result |
|---|---|---|
| `client-heed5-211824` (fresh) | `heed_rows.py` | **18/18** (new: the counts by kind no larger than the row's count allows, the centre within its square, and the row's field set exactly the listed fields) |
| `client-suite5-211824` | `run.py` | drive **45/45**, cues 23, near-tier 7, motion tables 34, combat feed 17, lines table 18, tick marker 5; no FAIL |

The game client (from heed-client): `HeedInput` built with `pin_at: None`, its test rows filled with the new columns' defaults; `cargo build --release -p living-game` and its `heed` and `throng` tests (12) pass. verify-ui was not driven.

**Not covered:** verify-ui's `heed-throng` scene on this branch; colours and kinds through a client on a world with looks and animals. Evidence: `.local/living/verify/client-heed5-211824/heed_rows.json`, `client-suite5-211824/results.md`.
