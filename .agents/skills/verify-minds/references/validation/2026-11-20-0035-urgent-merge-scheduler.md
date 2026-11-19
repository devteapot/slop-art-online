# Urgent merge with the scheduler fixes

The scoped pass ran the release mind at `1a770e94` on pinned main `48550720`, on a private SpacetimeDB 2.14.1 container (`slop-urgent-opus-stdb`) with loopback fake providers. Later commits are test-only, and `5fb3cb6f` has the same runtime code. The pass covered three scheduler changes ([Mind harness §8](../../../../../docs/MIND_HARNESS.md#root-cause-of-the-ordinary-tail-2026-11-19)):

- turns prepare in the order they will be served, and a lane keeps a turn it misses while preparing;
- any waiter grants for every ticket;
- the preparation lookahead has no floor.

| Check | Result |
| --- | --- |
| `urgent-merge` | 7/7. Walker3–5 were all in the first prompt. Its turn recorded `merged` 2 and an 11.722 s wait to prepare, behind the one slot held by another mind's 15 s think. Walker6 came alone in the follow-up. |
| `reasons`, `scene-since`, `animals` | Passed. |
| `lod` | Passed: urgent release in 0.37 s, and the merged non-plan reason was handled. |
| Living-mind unit suite | 131 passed, 15 ignored. The suite includes `steady_urgent_turns_leave_routine_turns_their_share`, `a_backlog_prepares_in_parallel_when_slots_are_free`, `a_held_up_ticket_does_not_stop_the_grants` and `a_turn_behind_a_long_call_prepares_when_its_slot_frees`. |
| `just living-check` | Through the build slot, exit 0. |

Earlier pass `minds-uo-vf` at `4b5cd4c8`, with a lookahead floor of one ticket per sixteen slots:

- **`urgent-merge` failed.** The waiting turn was nominated at once, a whole 15 s call before its grant. Only two blows were read, so `merged` was 1. The no-floor lookahead (`1a770e94`) fixed it.
- **`lod` failed its 10 s window.** Each routine install's reducer round trip took about 3 s on a host at load 15–36. The same case passed in this run.

Evidence: `.local/living/verify/minds-uo-vf2*` and `minds-uo-vf*` in the urgent-merge worktree, archived in `~/slop-evidence/urgent-merge-opus-20261120.tar.zst`.
