# The world's own law values (`law_override`)

Since `law-override` (2026-11-19, [docs/LAW_OVERRIDE.md](../../../../docs/LAW_OVERRIDE.md)).

**Visibility:**

- `law_override { name, value, revision }` is **public**: every law value the world sets over its script, for clients to lay over the compiled script (`living_rules::script::overrides_of`, `Scripts::with_overrides`, `apply_overrides`).
- It is read-only: only `set_world_law` writes it, and that reducer is admin only. A player's call is refused "admin only", with nothing written.
- `law_revision`, the authority's cache key, is **private** (in `PRIVATE`).

**First result:** a client's first subscription result holds every row, on a fresh connection before and after an edit.

## Driving it

The fixed suite's source inventory checks that `law_revision` is private, and the reducer matrix covers `set_world_law` per identity ([permissions.md](permissions.md)). The probe lists `law_override` among its tables, so `drive.py --query "SELECT * FROM law_override"` records its rows.

verify-core's `law_override.py checks --run "$R"` proves the rest on any launched and doctored run:

- anonymous SQL reads every row, and `law_revision` is refused;
- the player's `set_world_law` is refused;
- each of two fresh anonymous probe connections (`drive.py --query … --seconds 1`) gets the rows, with the value in force, in its `initial` event: one before a `near_tier_on` edit and one after it.

Evidence: `law-checks.json`, `law-first-before.jsonl` and `law-first-after.jsonl`. See [verify-core's law-override.md](../../verify-core/features/law-override.md).
