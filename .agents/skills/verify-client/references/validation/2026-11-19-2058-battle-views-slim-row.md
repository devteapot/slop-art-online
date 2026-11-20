# battle-views: the 98 B `seen_body_copy` row (verify-client)

Follows `2026-11-19-1851-battle-views.md`. The public motion copy row is now `viewer` (32 B), `body` (4), `near` (1) and `seg` (a `Segment`: the view's `Moving` without its id, 61 B): 98 B, was 106. No primary key: the frames find a viewer's copy by the `(viewer, body)` index; a change reaches a client as a delete and an insert. Server: the worker's own `bv-stdb` (v2.14.1).

- `motion_tables.py`: `client-bvs2` 19 of 19, then with the end-of-stream replay keyed by (viewer, body) and one more check ("A's table holds only A's rows at the end"), `client-bvs3` 20 of 20. Its replay of `seen_body_copy` is a set of rows (the probe streams from the connection on, so initial rows arrive both as inserts and in the snapshot; the first version counted them twice and failed "law off: … ends empty" on `client-bvs1`, a script defect, fixed).
- Mutation proof, `client-bvsmut2`: the same module without `SEEN_BODY_COPY_FILTER` fails 10 of the 20 checks (every isolation check, "only A's rows", and the rows-return check). The earlier crash of `client-bvsmut` (a duplicate guard in the replay raised on another viewer's rows) is why the replay now keys by viewer.
- Suite, `client-bvslim`: exit 0; drive 45 PASS; `cues.py` 21 of 21, `near_tier.py` 7 of 7, `motion_tables.py` 20 of 20.
- Scene gate, cases `cues` and `motion_tables` on `bv-stdb`, `gate-1119215556`: both pass.
- The probe streams `seen_body_copy` with insert and delete events only (no `on_update` without a primary key).

Evidence: `.local/living/verify/client-bvs3/`, `client-bvsmut2/`, `client-bvslim/`, `gate-1119215556-a-client/` (worktree, not in git).
