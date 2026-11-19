# doing-renew, pacing-neutral: a resident resting on, as a player's client receives it (verify-player)

This follows [2026-11-19-1920-doing-renew](2026-11-19-1920-doing-renew.md), which covered the first design (the leaf begun again at once). Now the `doing` row is held as it was until the body's next evaluation, which renews it in place; nothing begins sooner. Branch `doing-renew` at `67527f4c`, on main `440ca6a7` (both delivery laws on). Server: the worker's own `slop-doingrenew-stdb` (v2.14.1).

## Runs

- **`player-hold2`, `rest_seen.py`: 7/7.**
  - In 30 s, `seen_doing` and `seen_doing_near` each got 3 updates, 0 deletes and 0 inserts.
  - The renewals began 549, 1001 and 1000 ms after the last rest ended, the old pace, with `since_ms` kept.
  - `seen_doing_cue` got 3 cues, 0 of nothing.
  - Walked off: a cue of nothing at 38 ms, the near copy deleted at 363 ms.
- **Main `3df6e1f1`** (the same authority as `440ca6a7`; `player-main2`, recorded in the first record): 3 deletes and 3 inserts per stream, absent 505–1137 ms, and 6 cues, 3 of them of nothing.
  - The hold halves what the player's client is sent for a resting neighbour: 3 updates and 3 cues against 6 row changes and 6 cues.
- **`player-hold1`** (the earlier commit that wrote `until_ms` 0 at the hold): 7/7, with 6 updates and 6 cues. Superseded.

## Not covered

- The game client itself, and verify-ui: no client code changed, and the client's 1.6 s seat hold stays as a backstop.
- A far-tier viewer.

Evidence (worktree, not in git): `.local/living/verify/player-hold1/`, `player-hold2/`; archived in `~/slop-evidence/doing-renew-hold-20261119.tar.zst`.
