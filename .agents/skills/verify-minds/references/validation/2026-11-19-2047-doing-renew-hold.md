# doing-renew, pacing-neutral: a resting resident is seen resting just after a rest ends (verify-minds)

This follows [2026-11-19-1925-doing-renew](2026-11-19-1925-doing-renew.md). The second pass that began the next rest at once is replaced: the `doing` row is held until the next evaluation, and `perception::doing_of` names a held row's skill, so the scene's `doing` field says `rest` too while no activity runs. Branch `doing-renew` at `67527f4c`, on main `440ca6a7`. Server: the worker's own `slop-doingrenew-stdb` (v2.14.1). The real `living-mind` release binary ran against the fake model; no paid calls. `--no-unit-tests`: living-mind's tests ran in `just living-check` instead.

## Runs

- **`minds-hold2`, `doing-renew`: pass.**
  - Asked 183 ms after one of the other's rests ended (now inside the second before the next rest begins).
  - The pending request's scene lists the other with `doing: rest` and `visibly` `{is: rest, phase: under way}`, and the think prompt carries it.
- **`minds-hold2`, `doing`: pass.**
- `minds-hold1` (the earlier commit that wrote `until_ms` 0 at the hold): both passed.
- **Main**, as recorded in the first record (`minds-renew0`): asked at +133 ms, the scene had neither `doing` nor `visibly` for the other.

## Not covered

- The scene gate's minds cases (`roundtrip`, `acts`, `dealings`, `conversation`).

Evidence (worktree, not in git): `.local/living/verify/minds-hold1-*`, `minds-hold2-*`; archived in `~/slop-evidence/doing-renew-hold-20261119.tar.zst`.
