# Reducer permission matrix

## Sub-features

- Try every admin reducer as three non-admin client identities and without an HTTP token.
- Try every `mind_*` reducer on a seeded AI character and another player's character.
- Try every `mind_*` reducer on each identity's own joined character.
- Try `tick` and `housekeeping` from external clients.
- Join, move, act, and speak as players, and observe resulting subscription rows.
- Distinguish a fresh anonymous HTTP request from the persistent identity created by an anonymous WebSocket connection.

## How to get to it (user POV)

A client invokes reducers with its own identity. `require_admin` (`living/authority/src/lib.rs`) compares the sender with the world's admin (`create_floor` checks it inline, `floor.rs`). `authorize` (`living/authority/src/mind.rs`) compares the sender with the actor's controller; `mind_update` uses `authorize_projection`, which also accepts the admin for a character a person plays.

`join`, the `human_*` reducers (`lib.rs`) and `use_skill`/`release_skill` (`combat.rs`) are public. They require the sender's living non-AI character, found through the private `player` row (`perception::player_character`; a person with no row yet is found by its controller and the row is written). `tick` and `housekeeping` (`tick.rs`) and `genesis_step` (`floor.rs`) allow only the database identity, and this version does not expose scheduled reducers through the external call endpoint (HTTP 404).

## Driving it with drive.py

```bash
.agents/skills/verify-client/scripts/drive.py --run "$R"
```

`reducers.md` records every identity, reducer, HTTP status, response, and verdict. The mind service connects as the world's admin, so `require_admin` cannot refuse it an admin reducer by identity: before any call, `drive.py` fails if `living/mind/src` calls `admin_set_vitals`, `kill`, `relook`, `set_world_law`, `install_script` or `backfill_sex` (`never_by_minds`). `reducers.json` also records arguments and expected text. The copied admin and mind inventories must match the source before any calls run.

| Caller and target | Expected result |
| --- | --- |
| Non-admin calls to every admin reducer (`ADMIN` in `drive.py`, `admin_set_vitals` and `backfill_sex` among them since 2026-11-13) | HTTP 530, `admin only` |
| `mind_*` on an AI or another player's actor | HTTP 530, `not your character` |
| `mind_*` on the caller's own joined actor | HTTP 200 |
| External `tick` or `housekeeping` | HTTP 404, `No such procedure` |
| First `join` for a persistent identity | HTTP 200 |
| Duplicate `join` while that character lives (or while the person has a `presence` row) | HTTP 530, `you already have a living character` |
| `join_as(name, sex)` (sex-1) with a sex other than "f" or "m" (also "female", "male", any case), from anyone | HTTP 530, `sex must be "f" or "m"`, nothing made |
| `join_as(name, "f")` while that character lives | HTTP 530, `you already have a living character` |
| `join_as` for a fresh identity with "f" | HTTP 200; its `my_sex` row says "female", and SQL on `sex` is refused to it |
| `use_skill` / `release_skill` as a joined player | HTTP 200 (a refusal is told through `my_combat`) |
| `use_skill` / `release_skill` without a living character | HTTP 530, `you have no living character` |
| Joined identity's `human_move`, `human_act`, `human_say`, `human_speak(text, 0, "say")` | HTTP 200 |
| Joined identity's `human_speak` in a way the rules do not have | refused: "no way of speaking called `no_such_way`" |
| Tokenless HTTP `human_*` without a character | HTTP 530, `you have no living character` |
| Tokenless HTTP `join` | HTTP 200 for that request's new identity |

Own-character `mind_routines`, `mind_install`, `mind_install_way` (since `mind-say-way`), `mind_say`, `mind_act`, `mind_skip`, `mind_consolidated`, `mind_update`, `mind_judged` and `mind_where` (since `talk-places`: it writes the character's private `standing` row) are currently allowed for non-AI players. Since `attention-cues` the fixture's `mind_update` carries a cue (`MindUpdate.cues`): refused like the rest for another's character and for anonymous; for one's own played character it succeeds and keeps no cue (`mind.rs` `mind_update`: a played character sees with its player's eyes). The driver checks the owner's `cue` snapshot holds no row for the three identities' characters (`cues-owner.json`). Authorization does not require `ai = true`. The fixtures install a routine and plan, project a persona, append scripted thoughts, submit a signal act, and set an integration cursor. This is current controller authority, not an inference about intended product policy.

`reducer-effects.json` must contain each actor's routine, scripted thought references, the later `your command` plan, and speech chronicle line. A HTTP 200 proves acceptance; the subscription rows prove these effects.

## Gotchas

- HTTP requests without a token do not retain a useful identity across calls. The anonymous WebSocket client's issued token travels through an inherited pipe for later calls under that same identity. Neither identity is the admin.
- `mind_say` sends empty speech so the following `human_say` is not refused by the speech rate limit.
- The scheduled HTTP error occurs before the module's internal sender guard. Keep the actual 404 in the evidence.
- `mind_act` acceptance does not prove a queued signal physically succeeded. Use `verify-core` or `verify-player` for that outcome.
- Admin argument fixtures use zero spawn counts and zero grants. These calls still must be refused; an unexpected acceptance fails the matrix.

The fast lane's reducers (docs/FAST_LANE.md, since `fast-lane`, 2026-11-12): `mind_patch` and `mind_fast_done` need the caller to be the character's controller and an open fast request (`fast_ask`) issued at the given time. Anonymous callers and players are refused for another character ("not your character"), and a player for its own ("no fast re-plan was asked of this character"): a body its person controls never has a request (`drive.py` `FAST`).
