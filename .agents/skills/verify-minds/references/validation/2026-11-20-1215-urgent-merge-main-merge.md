# Urgent merge after merging main `ca2cee6a`

Follows [2026-11-20-0035-urgent-merge-scheduler](2026-11-20-0035-urgent-merge-scheduler.md). The scoped pass ran the release mind at `1767c824`, which is `urgent-merge` with main `ca2cee6a` merged (staged genesis, sweep-exact, ai-trims, rustc 1.99.1). It ran on a private SpacetimeDB 2.14.1 container (`slop-urgentab-20261120`) with loopback fake providers. Suite `minds-ab2-vf-124526`.

| Check | Result |
| --- | --- |
| `urgent-merge` | 7/7. Walker3–5 were all in the first prompt. Its turn recorded `merged` 2 and an 11.656 s wait for its turn, behind the one slot held by another mind's think. Walker6 came alone in the follow-up. |
| `reasons`, `scene-since`, `animals` | Passed. |
| `lod` | Passed: urgent release in 0.33 s, and the plain and merged reasons were both handled. |
| Living-mind unit suite | 137 passed, 15 ignored. |
| `just living-check` | Through the build slot, exit 0. The only failure was the listed known-red `look::tests::the_island_wears_the_pool`. |

The quiet-host A/B on the same head did not pass its one-sided latency check ([Mind harness §8](../../../../../docs/MIND_HARNESS.md#ab-on-main-ca2cee6a-quiet-host-2026-11-20-the-branch-is-slower)). These scenes prove behavior, not latency.

Evidence: `.local/living/verify/minds-ab2-vf-124526*` in the urgent-merge worktree, archived in `~/slop-evidence/urgent-merge-ab2-20261120.tar.zst`.
