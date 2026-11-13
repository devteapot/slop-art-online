# verify-client: admin-set-vitals, evidence restored

Follows `2026-11-13-0015-admin-set-vitals.md`, which stays as written. Its raw evidence (`core-vit-010444`, `core-vit2-010520`, `core-vit3-011233`, `core-vitmig-011000`, `client-vit-010544`, `client-vit2-011253`) was lost: it lived in the `admin-set-vitals` worktree's `.local/living/verify`, removed after the branch merged and before the archive-before-removing rule (2026-11-13). These reruns replace it, on origin/main `7f21e425` (admin-set-vitals merged as `60891e00`). Trial service `slop-trials-stdb`, `scoped`, private `CARGO_TARGET_DIR`, builds through `~/slop-mq/build-slot`.

- **verify-core `admin_vitals`** 7/7 (`core-vitr-031346`): 40 set and read back; 1000 read as the maximum; two `admin` chronicle lines; 0 refused, writing nothing; refused after `kill`.
- **verify-client suite** 43/43, no failures (`client-vitr-031508`).
  - Permission matrix: 267 calls. `admin_set_vitals` was refused "admin only" (HTTP 530) to anonymous-connected, player-1, player-2 and tokenless HTTP.
  - The `never_by_minds` source guard passed.
  - Cleanup confirmed by SQL 404.
- **Not rerun:** the migration check (`core-vitmig-011000`: a world from the module before the reducer, updated in place). Now that the reducer is on main, the same check would need a module from before `60891e00`; its result stays as the earlier record states, without its evidence.
- **Evidence:** `~/slop-evidence/restore-vitals-evidence-20261113.tar.zst` (sha256 beside it; both runs and the client run's log, 201 files).
