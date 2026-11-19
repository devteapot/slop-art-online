"""The world's own law values as a verification script or trial reads them (docs/LAW_OVERRIDE.md).

    from law_values import own_laws          # living/tools on sys.path
    laws = own_laws(lambda q: rows(q))       # {name: value as JSON text}

Since `law-override` (2026-11-19) a world keeps its own law values (a seed's `rules`,
`set_world_law`) in the public `law_override` table; `world_law` is copied into it once and no
longer written. A module from before (main before law-override, a trial's "before" arm, an older
wasm tag) has only `world_law`. `own_laws` reads both and lays `law_override` over `world_law`, so
it gives the values in force on either module: on a new module `law_override` holds every value
(the copied rows included), and `world_law` holds nothing newer. `query` is the caller's own SQL
helper (owner identity for `world_law`, which is private): it takes a query and returns rows as
dicts. Standard library only.
"""


def own_laws(query):
    """{law name: value as JSON text} in force as the world's own, from `law_override` over `world_law`.

    `world_law` exists on every module (kept on new ones), so its query must succeed: a helper
    that cannot read it (a wrong identity, a wrong call) is an error, never an empty answer. Only
    `law_override`, missing on a module from before it, may fail and count as no rows."""
    out = {r["name"]: r["value"] for r in (query("SELECT name, value FROM world_law") or [])}
    try:
        over = query("SELECT name, value FROM law_override") or []
    except TypeError:
        raise
    except (Exception, SystemExit):
        over = []
    for r in over:
        out[r["name"]] = r["value"]
    return out
