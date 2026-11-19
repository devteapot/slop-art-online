# Frame views client validation

Branch `frame-views-client`, client commit `5a901536c848e8a5426f452c56ad626dbec03d65`, built on authority commit `f9d90976928f28846248d9b32d7438ee22800e26`. The scratch worlds used the island seed, scoped perception and the local SpacetimeDB 2.14.1 image. The client and SDK probe used private target directories. Scene placement, noon and fixture setup used the scratch world's admin. Player movement, gestures and strikes used separate player identities. No mind service or model ran.

## Protocol and scope

The six tier views and three event tables ship in the authority branch's generated bindings. The client uses the public `Moving`, `Fighter` and `Doing` row shapes. The private copy rows' `near` fields are handled by the generated bindings and consumed only by the authority. The declaration in `net.rs` pairs each SDK accessor with its SQL name and cue payload mapping.

- Subscriptions initialize the durable cache and then deliver committed deltas. The three streams join the player's existing perception subscription. The nearby and distant tiers partition each stream. [Subscriptions](https://spacetimedb.com/docs/clients/subscriptions/) · [Subscription semantics](https://spacetimedb.com/docs/clients/subscriptions/semantics/) · [Views](https://spacetimedb.com/docs/functions/views/)
- Cue event tables deliver inserts without retaining rows in the client cache. RLS filters the cue query by viewer identity. The player overlays hold at most one value per visible creature per stream. Tier changes invalidate that stream's overlay and losing body visibility drops its remaining optional overlays. [Event tables](https://spacetimedb.com/docs/tables/event-tables/) · [Row-level security](https://spacetimedb.com/docs/how-to/rls/)
- The pinned Rust SDK applies the transaction to the cache before delivering row callbacks. Tier changes are keyed by creature ID, so changing tiers does not make a creature briefly invisible to cue handling. [2.14.1 table API](https://github.com/clockworklabs/SpacetimeDB/blob/v2.14.1/sdks/rust/src/table.rs) · [2.14.1 cache update and callbacks](https://github.com/clockworklabs/SpacetimeDB/blob/v2.14.1/sdks/rust/src/db_connection.rs)
- Reviewed the game client's subscription entry points. `net.rs` subscribes the player connection to explicit static, perception and spatial query lists. The separate scratch admin link in `facing.rs` sends `set_world_law` without subscribing. The game has no subscribe-all call. The observer and mind service use explicit query lists with no frame cue subscriptions.

## Game client checks

`cargo test --manifest-path living/Cargo.toml -p living-game` passed 129 tests with one ignored. The release-profile run had the same result. The final release client drove the fresh cues-on motion and camera rerun and the reconnect fixture.

| Scenario | Cues and tiers | Tier-only client |
| --- | ---: | ---: |
| camera | 60 passed | 60 passed |
| talk | 22 passed | 22 passed |
| far | 11 passed | 11 passed |
| look-walk | 91 passed | 91 passed |
| reversal | 5 passed | 5 passed |
| Total | 189 passed, 0 failed | 189 passed, 0 failed |

- The first cues-on run returned 178 passes and 9 failures. The six roof-cutaway and two hover-label failures cleared with the full read-only asset links. The look-walk case missed the other player's motion while the camera fixture's facing-sight law was still on. On a fresh world, running camera after motion gave 156 passes across camera, look-walk and reversal. That rerun supplies those three results above. The initial run supplies the 33 talk and far passes.
- The tier-only column uses a temporary client with the three cue queries omitted and the same overlay and tier fallback logic. The authority in this run continued to produce frame cues. A true no-cue server state remains untested.
- Each look-walk run covered Head, Chest and Loose, settings persistence and the second-player motion case. The reversal case drove a second player's direction change with their look held aside.

Evidence is in `.local/living/verify/ui-frame-views-client/ui/checks.json`, `.local/living/verify/ui-frame-views-camera-assets/ui/checks.json` and `.local/living/verify/ui-frame-views-client-tiers/ui/checks.json`, with client logs, scene recordings and stills beside each file. The harness deleted every scratch database and kept the evidence.

## SDK delivery

`verify-client`'s `cues.py` passed 14 checks. Separate player identities and an anonymous observer exercised RLS, near/far partitioning and convergence while the partner stepped, waved and struck. The near partner was 1 m away and the far fixture 10 m away at start. The capture lasted 28 seconds with three player identities and an anonymous SDK connection, plus a short extra query from one player. This is a smoke fixture.

The age of a distinct near motion segment is its first SDK callback wall time minus the authority's segment `t_ms`. The samples come from the action window and use nearest-rank p90.

| Input examined | Segments | p50 | p90 |
| --- | ---: | ---: | ---: |
| Cues and tiers | 11 | 19 ms | 27 ms |
| Near tier deliveries from the same capture | 9 | 225 ms | 398 ms |

Two segments observed through cues did not reach the near tier before being superseded. The tier-only calculation filters one capture with cues enabled on the server. The result measures SDK delivery on this laptop and fixture. Evidence is in `.local/living/verify/client-frame-views-client/{sdk-cues-checks.log,cues.json,motion-age.json}`.

## Spec differences

- The branch's Client change section admits fighter and doing cues when the creature is visible in either motion tier. This supports a cue introducing or clearing an optional action before its next tier row. The initial summary described a stricter per-stream membership check.
- This authority commit calls the frame cue pass unconditionally. The existing `cues_on` law governs mind attention cues. A server-law-off verify-ui run and a server-law-off motion age measurement require the transport law from dev-box.

## Reconnect

On `verify-ui-frame-views-reconnect-3` the headless game used a loopback TCP proxy for its own player connection. A nearby player walked and changed direction, a second struck, and a third waved. The driver dropped that socket after receiving a trace line for the walking player's motion cue. It stopped the walker and placed that player at a different position during the disconnect. The initial subscription after reconnect rebuilt all three overlay maps and recovered the stationary tier pose.

All five checks passed. The old connection logged **2 motion, 1 fighter and 1 doing** entries. The new connection logged **0, 0, 0** before it subscribed. The proxy accepted two connections and dropped one. The walker was drawn in 161 post-reconnect frames and the final ten differed from the authority's stationary position by 0 m. Two earlier attempts also resubscribed and recovered the exact pose with fighter and doing entries live at disconnect. They did not catch a live motion overlay in the drop window.

Evidence is in `.local/living/verify/ui-frame-views-reconnect-3/reconnect/{result.json,client.log,feet.jsonl,recovered.png}`. The earlier attempts are under `ui-frame-views-reconnect` and `ui-frame-views-reconnect-2`.
