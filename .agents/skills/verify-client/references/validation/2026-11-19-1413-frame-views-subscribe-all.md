# frame-views: subscribe-all and the tiers' switch (verify-client)

Follows `2026-11-19-0914-frame-views-review.md`. Branch `frame-views` at `defc3e7bf`'s code (`near_tier_on`, the fixed frame charge) with `cues.py`'s new probes. Server: the worker's own `views-stdb` (v2.14.1, 127.0.0.1:3344).

- `cues.py`, `client-viewsq-1411f`: 21 of 21. New: player C subscribing every public table by name (what the SDK's `subscribe_to_all_tables` sends, cue tables included), accepted, received no one else's cue; C's `SELECT * FROM *` (the server's own expansion, which leaves event tables out at `v2.14.1`, `subscription.rs` `get_all`), accepted, received no cue. Earlier today `client-viewsq-...d`/`e`: 19 of 19 (before the new probes).
- `near_tier.py`, `client-viewst-...d`: 7 of 7, with the new `near_tier_on` off phase (the near tier empty, the far tier holding everyone) and back on.

Not covered: the open build; the game client (the laptop's `frame-views-client-v2` checks all four law states).
