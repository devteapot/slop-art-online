# Frame views client v2 validation

Follows `2026-11-19-0003-frame-views-client.md` on branch `frame-views-client` (commit `f41aa758d`, built on the older authority `f9d90976`); that record is not on this branch.

- **Branch:** `frame-views-client-v2`, based on `origin/frame-views` at `461c4c5d34b05b8f0d477e71173925272fe17b0a`.
- **Client change:** the old client commit `5a901536c` cherry-picked cleanly, plus the `cue_transport_on` handling below. The scratch worlds ran the module built from this branch's authority, with no authority change.
- **Setup:** the laptop's shared `sao-living_spacetimedb_1` (v2.14.1), the island seed and a `scoped` build. Builds used private target directories. No mind service ran and no model was called.

## Protocol

The authority now keeps the near tier in three private tables (`motion_near`, `fighter_near`, `doing_near`), not in a `near` column. The public names and row shapes are unchanged: `seen_{bodies,fighters,doing}_{near,far}` (`Moving`, `Fighter`, `Doing`) and `seen_{body,fighter,doing}_cue`. The client therefore keeps the old stream-name table (`perception_streams!` in `net.rs`).

The bindings on `frame-views` are current. A fresh `spacetime generate --include-private` from this module was identical to `living/bindings/src/generated` after rustfmt, so they were not regenerated.

New in the client:

- **`net::cue_law`.** It reads `cue_transport_on` from the installed `skills` script, which the client already compiles (`verbs::Rules`; the authority writes a world's own law values into it). It reads the law once per script revision and passes it to the connection's overlays every frame.
- **Law off.** All three overlays are cleared and no cue is taken. This matches the spec ("turning off clears all too").
- **Before the script compiles,** cues are taken. While the law is off, the authority writes none.
- **The live report** (`live.rs`) adds `cue overlays (M, F, D)`.
- **Trace lines** for accepted fighter and doing cues are added, as motion already had.

**Viewer scope.** Only the player's connection subscribes. `facing.rs`'s admin link calls `set_world_law` and subscribes nothing, and the game has no subscribe-all.

Docs read (shown version 2.0.0):

- [Event tables](https://spacetimedb.com/docs/tables/event-tables/): `on_insert` only, rows never cached, and RLS applies with table semantics.
- [Subscription semantics](https://spacetimedb.com/docs/clients/subscriptions/semantics/): the cache is applied before callbacks, with no order between tables or callbacks. The overlays therefore key each change by creature and check the post-transaction cache.
- [Views](https://spacetimedb.com/docs/functions/views/) and [RLS](https://spacetimedb.com/docs/how-to/rls/) (experimental, `unstable`).

## Client tests

`cargo test --release -p living-game`: **130 passed, 1 ignored.** That includes the new `net::cue_tests::cue_transport_off_clears_every_overlay_and_on_takes_cues_again`.

## verify-ui per law state

Each state ran on a fresh world, `ui-fv2s-{on,cuesoff,tiersoff,bothoff}`. The laws were set with admin `set_world_law` after launch. Each client logged `rules: cue_transport_on true|false` as set. The scenarios ran in this order: talk, far, look-walk, reversal, then camera.

| State (`cue_transport_on`, `near_tier_on`) | camera | talk | far | look-walk | reversal | Total |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| all on (true, true) | 60 | 22 | 11 | 91 | 5 | 189 / 0 failed |
| cue transport off (false, true) | 60 | 22 | 11 | 91 | 5 | 189 / 0 failed |
| near tier off (true, false) | 60 | 22 | 11 | 91 | 5 | 189 / 0 failed |
| both off (false, false), main's delivery | 60 | 22 | 11 | 91 | 5 | 189 / 0 failed |

A first all-on attempt (`ui-fv2-on-paused`) is void:

- It passed 77 checks and failed 12, in look-walk, reversal and camera.
- The cause was the harness: the world was launched under `build-slot`, whose shell exited, and the orphan guard paused it at 13:26 (`world-guard.log`). Every drive after that saw no one: `perceived` held 0 rows for the player, beside 21 bodies within 20 m.
- Launching from the long-lived driver (`.local/fv2/states.sh`) fixed it.
- Cleanup also refuses a world whose `epoch_ms` differs from the run record, and the UI noon fixtures change it. The driver restores the recorded epoch before `cleanup`.

## SDK delivery and scope (`client-fv2`)

- **`verify-client` `cues.py`: 19/19.** RLS keeps each cue to its viewer. C, the anonymous connection and B's peek by A's identity got none. The near partner's six windups arrived first by cue, 12–25 ms after `act_ms`. The tiers partition the views, and the client's replay rule ends on the views' rows. With the law off, no cue reached anyone and the windups came by the near tier in 19–43 ms.
- **`near_tier.py`: 7/7.** `NEAR_MAX` 32: the 32 nearest of 33 strangers are near. An engaged player at 10 m joins at once, past the cap, and is first at the next sweep. With `near_tier_on` off, the near tier is empty and the far tier holds everyone seen.

## Near-motion age at the SDK

The fixture (`.local/fv2/motion_age.py`):

- Two fresh players stood 1 m apart on a quiet open line of the island, with no other body within 30 m.
- One SDK probe ran on A with the client's motion set: both tiers, `seen_body_cue` and `my_body`.
- B walked a small octagon, with a new `human_move` every 0.75 s for 40 s (53 inputs, at most 5.7 m from A).
- Age is the probe's receipt time minus the segment's `t_ms`, taken at the first row (either tier or a cue) whose `t_ms` is newer than the last held. Percentiles are nearest-rank.
- This is a single viewer on a quiet laptop, a smoke measure only. It is not the 216-player series.

| State | Segments | p50 | p90 | max | First by | Rows for B (near / far / cue) |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| cues and tiers on | 69 | 18 ms | 26 ms | 32 ms | cue 67, near 2 | 61 / 0 / 69 |
| cue transport off | 69 | 27 ms | 41 ms | 58 ms | near 69 | 70 / 0 / 0 |
| near tier off | 69 | 28 ms | 46 ms | 55 ms | far 69 | 0 / 70 / 0 |
| both off | 69 | 31 ms | 44 ms | 54 ms | far 69 | 0 / 70 / 0 |

With the near tier off and cues on, no cue was written: nobody is near, and B was not engaged with A.

## Reconnect mid-movement, cues on (`ui-fv2s-recon`)

The fixture (`.local/fv2/reconnect.py`):

- The headless client's own connection went through a loopback TCP proxy; the harness's calls went direct.
- Three fresh players stood beside it on Brackenford's square. B walked (a new `human_move` every 0.75 s), C struck at D every 1.6 s, and D waved at the player every 3 s.
- Once the client had taken a motion, a fighter and a doing cue, the proxy dropped the socket right after a motion cue for B.
- During the disconnect, B stopped and was placed 3 m away, and C and D stopped.

Results:

- **Overlays at the drop: (1, 3, 2).** The old connection logged that; the new one started at **(0, 0, 0)**. The proxy accepted two connections and dropped one.
- **No stale overlay.** B was drawn exactly where the authority held it, 0.000 m off over the last 10 frames, with B logged in 3,600 frames. After the reconnect no cue of B, C or D was taken, and no live report showed a fighter or doing overlay.
- **Two checks as first written failed: "no cue after the reconnect" and "all reports (0, 0, 0)".** They assumed an empty scene, but 129 cues of 12 residents walking the square arrived after the reconnect, and the first report showed (2, 0, 0). Re-scored on the fixture's own players from the same log (`result-rescored.json`), all four checks pass: cues of B, C and D taken before the drop (12 motion, 6 fighter, 5 doing); the drop right after B's motion cue; none of theirs after; no fighter or doing overlay in any later report.

## Spec notes

- No spec and code disagreement in what the client relies on.
- `docs/TICK_RATE.md` says a subscribe-all query skips event tables in 2.14.1's source. The current event-tables page says subscribe-all helpers include them. That was not verified here, and the game client subscribes no subscribe-all.

## Evidence

- `.local/living/verify/ui-fv2s-{on,cuesoff,tiersoff,bothoff}/ui/` (checks.json, logs, dumps, stills) and `.local/fv2/ui-*.log`.
- `.local/living/verify/client-fv2/` (cues.json, near_tier.json, motion-age.json and its jsonl streams).
- `.local/living/verify/ui-fv2s-recon/reconnect/` (result.json, result-rescored.json, proxy.log, feet.jsonl) and `ui/reconnect-client/client.log`.
- The void attempt is in `.local/living/verify/ui-fv2-on-paused/`.
- Every scratch database was deleted, and each name answered "no longer resolves".

## Not covered

- A law switched mid-drive on screen: the clearing on `cue_transport_on` off was covered by the unit test and the per-state client logs, not by a live switch under a drive.
- Scale, latency at 80 ms RTT, and the 216-player series.
- A real window.
