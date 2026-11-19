# frame-views: merged with main 8851982d2 (verify-client)

Follows `2026-11-19-1548-frame-views-gating.md`. Branch `frame-views` after merging `origin/main` (`8851982d2`, the seen-ranges laws, `my_senses_v2`, the procedures inventory, the `mechanics` gate group). `frame.rs` is unchanged by the merge; the `cue_transport_on` law is now on by default (since acceptance), and `cues.py` puts back `true` when a world has no row for it. Server: the worker's own `views-stdb` (v2.14.1). Host shared (load 3.8 at the start).

- `cues.py`, `client-viewsq-1632m`: 21 of 21.
- `near_tier.py`, `client-viewst-1632m`: 7 of 7.
- Scene gate, case `cues` only (`scene_gate.py run --force --cases cues --no-main-check` on `views-stdb`), `gate-1119173504`: passed in 105 s.
- Suite (`run.py`), `client-views-1632m`: the source inventory failed, `a program subscribes every table … ['.agents/skills/verify-client/scripts/cues.py']`. `cues.py` has subscribed every table as player C since 802116def to prove the subscribe-all case, and the guard, added before that, did not exempt it. It was not caught then because the suite was not run after 802116def. The guard now exempts `cues.py` by name, as it exempts `drive.py`. Rerun, `client-views-1745m`: 45 PASS, 0 FAIL, with cues and near-tier steps passing.

Evidence: `.local/living/verify/client-views-1745m/`, `client-viewsq-1632m/`, `client-viewst-1632m/`, `gate-1119173504-a-client/` (worktree, not in git).
