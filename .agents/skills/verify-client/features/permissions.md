# Reducer permission matrix

## Sub-features

- Try every admin reducer as three non-admin client identities and without an HTTP token.
- Try every `mind_*` reducer on a seeded AI character and another player's character.
- Try every `mind_*` reducer on each identity's own joined character.
- Try `tick` and `housekeeping` from external clients.
- Join, move, act, and speak as players, and observe resulting subscription rows.
- Distinguish a fresh anonymous HTTP request from the persistent identity created by an anonymous WebSocket connection.

## How to get to it (user POV)

A client invokes reducers with its own identity. `require_admin` at `living/authority/src/lib.rs:66` compares the sender with the world's admin. `authorize` at `living/authority/src/mind.rs:75` compares the sender with the actor's controller.

The `join` and `human_*` reducers at `lib.rs:312` onward are public. Human commands require the sender's living non-AI character. `tick.rs:13` and `tick.rs:299` allow only the database identity, and this version does not expose those scheduled reducers through the external call endpoint.

## Driving it with drive.py

```bash
.agents/skills/verify-client/scripts/drive.py --run "$R"
```

`reducers.md` records every identity, reducer, HTTP status, response, and verdict. `reducers.json` also records arguments and expected text. The copied admin and mind inventories must match the source before any calls run.

| Caller and target | Expected result |
| --- | --- |
| Non-admin calls to every admin reducer | HTTP 530, `admin only` |
| `mind_*` on an AI or another player's actor | HTTP 530, `not your character` |
| `mind_*` on the caller's own joined actor | HTTP 200 |
| External `tick` or `housekeeping` | HTTP 404, `No such procedure` |
| First `join` for a persistent identity | HTTP 200 |
| Duplicate `join` while that character lives | HTTP 530, `you already have a living character` |
| Joined identity's `human_move`, `human_act`, `human_say` | HTTP 200 |
| Tokenless HTTP `human_*` without a character | HTTP 530, `you have no living character` |
| Tokenless HTTP `join` | HTTP 200 for that request's new identity |

Own-character `mind_routines`, `mind_install`, `mind_say`, `mind_act`, `mind_skip`, `mind_consolidated`, and `mind_update` are currently allowed for non-AI players. Authorization does not require `ai = true`. The fixtures install a routine and plan, project a persona, append scripted thoughts, submit a signal act, and set an integration cursor. This is current controller authority, not an inference about intended product policy.

`reducer-effects.json` must contain each actor's routine, scripted thought references, the later `your command` plan, and speech chronicle line. A HTTP 200 proves acceptance; the subscription rows prove these effects.

## Gotchas

- HTTP requests without a token do not retain a useful identity across calls. The anonymous WebSocket client's issued token travels through an inherited pipe for later calls under that same identity. Neither identity is the admin.
- `mind_say` sends empty speech so the following `human_say` is not refused by the speech rate limit.
- The scheduled HTTP error occurs before the module's internal sender guard. Keep the actual 404 in the evidence.
- `mind_act` acceptance does not prove a queued signal physically succeeded. Use `verify-core` or `verify-player` for that outcome.
- Admin argument fixtures use zero spawn counts and zero grants. These calls still must be refused; an unexpected acceptance fails the matrix.
