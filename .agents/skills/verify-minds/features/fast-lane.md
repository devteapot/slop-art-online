# The fast lane

docs/FAST_LANE.md; `living/mind/src/mind/fast.rs` (serving an issued `fast_ask` row), `prompts.rs` `fast_system_v`, `fast_frame_text` and `fast_user_v`, `main.rs` (the `fast_ask` subscription and its channel), `rethink.json` `fast` (route, timeout, experiences). The world law `fast_lane_on` turns it on (off by default).

Frame (battle-frame, 2026-11-21; docs/FAST_LANE_FRAME.md): `LIVING_FAST_FRAME` is `first` (the default, the frame every earlier trial ran) or `balanced`; any other value stops the service at start. `living-mind fast-replay` sends saved fast requests again in either frame (`--prompts-only` makes no call).

Dispatch (fast-dispatch, 2026-11-20; docs/INPUT_LATENCY.md, "Mind dispatch profile"): the `fast_ask` insert and update callbacks send to the fast lane's own channel, read on its own runtime (`LIVING_FAST_WORKERS`, default 2), where the request is prepared and sent through the fast lane's own HTTP client. It never waits behind the shared event loop. With `LIVING_INPUT_LATENCY=1`, `outcomes/input_latency_fast.jsonl` stamps each ask (callback, dispatch, pickup, model start, queue entry, grant, reply, patch send).

## Cases (fake model; `LIVING_RETHINK_CONFIG` routes `fast` to the fake's profile)

`fast-lane` routes through a staged mix (compile by stage of attention, as the shipped models do), so the eye, which no player watches, is off stage for model routing; with the level of detail off, it is still served.

- `fast-lane`: the other strikes at the eye with a spear's heavy blow over and over.
  - (e) asleep: the eye sleeps; the other's one blow issues nothing.
  - (a) a blow taken issues one fast request; its prompt holds, in this order, who you are, the top level, the routines, why now (the eye's own line for the blow) and what has just happened (stable parts first, for the providers' prefix caches), and no count or "again"; the reply's `combat` branch is installed through `mind_patch` (source `fast`, a `fast` thought "… → combat branch rewritten").
  - (b) blows inside the 6 s gap merge: one request in the first 5.5 s.
  - (g) the slow deliberation the same blow started (its compile held 5 s) installs after the patch and keeps the patched `combat` branch.
  - (c) the next reply is held 2.5 s while an admin `set_behavior` changes the plan: refused by the plan check ("refused: the plan changed since it was asked").
  - (f) with `fast_lane_on` off, blows ask nothing.
  - The default frame is the first one: the system prompt lists no ways and the user prompt has no How you are now.
- `fast-frame` (`LIVING_FAST_FRAME=balanced`, docs/FAST_LANE_FRAME.md): one blow taken issues one fast request.
  - Its system prompt opens with the balanced frame: Why now set apart from what else is perceived, the six ways side by side from keeping to breaking contact, keep first among the replies.
  - Its user prompt is the first frame's with How you are now last: one line, "How your body feels: …", the eye's own felt body; no number and no count.
  - The reply (one line put first, the fight beneath it) is installed through `mind_patch` as a `combat` patch.
- `fast-takeover`: (d) a player's character the minds hold (`takeover_s` 5) is struck, and its reply is held 12 s.
  - The person's return deletes the request.
  - The minds take over again, and the late reply is refused by the authority ("no fast re-plan was asked of this character"); the body got no patch.

Evidence: `fake-requests.jsonl` (purpose `fast`), `fast-prompt.txt`, `mind.log`, `result.json`.
