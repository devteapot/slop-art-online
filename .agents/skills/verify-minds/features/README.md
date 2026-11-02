# Internal mind verification map

| Feature | Cases | File |
| --- | --- | --- |
| Think, compile, install, act, speak | `roundtrip`, `acts` | [deliberation.md](deliberation.md) |
| Answer speech and close an exchange | `conversation` | [conversations.md](conversations.md) |
| No-store persona/cursor, patch-loss XFAIL | `consolidation` | [consolidation.md](consolidation.md) |
| Validate graphs, restrict actors, recover connection | `prune`, `reject`, `only`, `reconnect` | [robustness.md](robustness.md) |
| Wait off stage and resume on stage | `lod` | [level-of-detail.md](level-of-detail.md) |
| Paid-wrapper dry safety and paid smoke check | dry safety; paid authorization required | [real-models.md](real-models.md) |

Each free case launches its own database through `verify.py` and passes doctor before driving the real mind binary. Admin calls arrange scenes only. Requests go through the production HTTP model boundary, and replies return through production mind reducers. Public snapshots use shared SQL; private deliberations use shared `sql --as-admin` with the token held in memory. Store-backed projections belong to `verify-knowledge`.

All evidence stays under `.local/living/verify/`. The paid tier is documented and intentionally unexecuted. Runtime discovery uses the shared `.agents/skills/` source and the existing Claude and Cursor links.
