# Deliberation preparation across model-queue turns

The scoped pass used the release mind, SpacetimeDB 2.14.1, C2 from the pinned `04b9ccc2` base, and loopback fake providers on a private Spark container. Prompt preparation keeps an existing queued ticket and uses a model slot only after it makes the ticket ready.

| Check | Result |
| --- | --- |
| `urgent-merge` | 7/7. Walker3, Walker4 and Walker5 appeared in the first prompt. Its turn recorded two merged lines and an 11.593 s wait to prepare. Walker6 appeared alone in the follow-up. |
| `reasons` and `scene-since` | Both passed, covering single consumption, follow-up reasons and the request scene's experience cutoff. |
| `lod` and `animals` | Both passed. The animal choice and the later salience skip were exercised live. |
| Living-mind unit suite | 126 passed, 14 ignored. `preparing_a_turn_leaves_the_model_slot_available` proved an ordinary call can use the only slot while another turn prepares. |
| Build and repository checks | `just living-check` through the build slot with pipefail exited 0. |

Evidence is in `minds-urgent-ab-verify` and its case folders, and the fixed-site benchmark is described in [Mind harness §8](../../../../../docs/MIND_HARNESS.md#fixed-site-follow-up-2026-11-18). The private-server evidence archive is `~/slop-evidence/urgent-merge-ab-20261118.tar.zst`.
