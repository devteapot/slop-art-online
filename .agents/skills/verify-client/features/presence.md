# Presence: whether a player is there, and who controls the character

Since 2026-11-09 (docs/PLAYER_MEMORY.md, "Presence and the offline character"). The `client_connected` and `client_disconnected` lifecycle reducers keep one private `connection` row per open connection, and a private `presence` row per played character says whether its person has one open. When the last closes, the minds take the character over after the `takeover_s` law (30 s); a new connection of its person hands it back inside `client_connected`, before the client subscribes.

## Sub-features

- One WebSocket connection of the player: `presence.present`, `connections` 1. A second at once: `connections` 2. One closed: still present, 1 (`presence.json`, steps "one connection", "two connections", "one closed").
- The last one closed: not present, `connections` 0, a takeover pending (`takeover_ms`), the character still the player's (step "both closed").
- After `takeover_s` with no connection: `presence.ai`, and the character's `controller` is the world admin (the mind service) with `ai`, on any seed (step "taken over").
- A new connection: `presence.ai` false, the character's `controller` the player's identity again, and `my_characters` returns it on that very connection (step "returned").
- Presence is private: refused to the player and to an anonymous client (`presence-player.json`, `presence-anonymous.json`); `connection`, `reveal` and `acquaintance` are in the private-table refusals (`visibility.json`).

## How to get to it (user POV)

A player opens the game (one connection) or two (a second tab). Presence follows each. Closing the game leaves the character standing; half a minute later it lives on by itself; opening the game again puts the player back in control at once.

## Driving it with drive.py

The fixed suite runs it last, on `ClientSecond` (joined over HTTP, so no connection is open before):

```bash
.agents/skills/verify-client/scripts/run.py --run "$R"
```

It holds probe connections open in threads (`presence-one` for 8 s, `presence-two` for 3 s), reads the presence and character rows as the owner at each step, waits up to 45 s for the takeover, then connects once more (`presence-back`).

## Gotchas

- HTTP calls are connections too: each runs both lifecycle reducers around the call. The takeover's `takeover_s` grace is what keeps an HTTP-driven player from flapping between calls. A driver that leaves more than 30 s between a player's calls sees its character taken over and handed back at the next call; a test that must not see that raises the law (an installed copy of skills.rhai with a larger `takeover_s`; `install_script` reschedules pending takeovers).
- The harness's own owner connections (SQL over HTTP) count only for the admin identity, which plays no character.
