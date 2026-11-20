# Scheduler fixes after merging main `ca2cee6a`

Follows [2026-11-20-0035-urgent-merge-scheduler](2026-11-20-0035-urgent-merge-scheduler.md). The local tier ran the release mind at `1767c824`, which is `urgent-merge` with main `ca2cee6a` merged. It ran on a private SpacetimeDB 2.14.1 container (`slop-urgentab-20261120`). Suite `llm-ab2-vf-124526`.

- **Fake-provider contract:** all ten scenarios passed.
- **`llm::tests`:** 37 passed, 2 ignored.
- **All 20 local cases passed:** `basic`, the five routing cases, `overflow`, `capacity-overflow`, `capacity-retry`, `retry-fallback`, `error-overflow`, `outage`, `repair`, `deliberation-retry`, `retry-exhausted`, `timeout`, `missing-default-key`, `mix`, `fast-route` and `fast-cap`.

Not covered: real providers (paid tier), pacing under real 429s beyond the fake contract, and latency under a battle. The quiet-host A/B on this head found the branch slower than main ([Mind harness §8](../../../../../docs/MIND_HARNESS.md#ab-on-main-ca2cee6a-quiet-host-2026-11-20-the-branch-is-slower)).

Evidence: `.local/living/verify/llm-ab2-vf-124526*` in the urgent-merge worktree, archived in `~/slop-evidence/urgent-merge-ab2-20261120.tar.zst`.
