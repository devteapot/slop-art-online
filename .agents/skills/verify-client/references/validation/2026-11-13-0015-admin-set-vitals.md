# verify-client: admin-set-vitals

Branch `admin-set-vitals` (one commit on origin/main `1dc58639`; driven with main `80e75932` merged in). Trial service `slop-trials-stdb`, `scoped`, private `CARGO_TARGET_DIR`.

- **The change.** The new admin reducer `admin_set_vitals` is in `drive.py`'s `ADMIN` inventory, so the permission matrix tries it as every non-admin identity.
  - New source guard: the mind service connects as the world's admin, so `require_admin` cannot refuse it by identity. `drive.py` now fails before any call if `living/mind/src` calls `admin_set_vitals`, `kill`, `relook`, `set_world_law` or `install_script` (`never_by_minds`). None does.
  - features/permissions.md says both.
- **The suite:** 43/43, with no failures, before and after merging main (`client-vit-010544`, `client-vit2-011253`).
  - Permission matrix: 267 calls. `admin_set_vitals` was refused "admin only" (HTTP 530) to anonymous-connected, player-1, player-2 and tokenless HTTP.
  - Cleanup confirmed by SQL 404.
- **Maintenance (scoped, no fan-out).** The features this touches were checked against the source:
  - verify-client: permissions.md (the matrix, the new guard);
  - verify-core: README's new row and needs.md "An admin sets a body's health".

  Both were driven live (this suite; verify-core `admin_vitals`). No other drift was looked for.
