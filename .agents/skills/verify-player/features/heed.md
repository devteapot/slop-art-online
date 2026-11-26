# Heed for players (`heed_players` with `heed_on`)

**What it is.** docs/ATTENTION_BUDGET.md, "Built: the player side". With both laws on (both off as shipped; value-only `heed_players`, ordinary `heed_on`), a played character's committed `perceived` set is its individuals: the sweep takes `heed::split` in place of `far_cap`'s trim, so the views, copies, cues and projections follow them. The rest of its sight is counted, never named, in the public `seen_throng` (6 m cells, row-level security `viewer = :sender`, written on change only). Contact puts the attacker into `perceived` in the blow's own tick. The player's pins and focus go through `human_heed(HeedInput { pins, focus })` into the private `heed_choice` row, read at each heed pass.

**Drive.** `scripts/heed.py --run "$R"` (any seed). Admin calls set the scene: `spawn_crowd`, `set_behavior`, `place_at`, `admin_set_vitals` and `set_world_law` (`heed_on`, `heed_players`, `heed_ceiling` 2, `far_cap`). It puts the laws back as the world had them and writes `heed-proof.jsonl`.

**Checks.**
- Off (as shipped): all eight walkers perceived; no `seen_throng` row.
- On, capacity 2: at most 2 perceived, among the nearest; `perceived` holds exactly those; `seen_throng` counts the rest and carries cells, counts and bits only; `far_cap` 1 on top changes nothing (heed replaces the trim).
- `human_heed`: five pins refused ("at most 4"); a throng member and an id no one has refused with the same words (`You can only keep track of someone you can see now.`); a second call within 250 ms refused (`too many inputs`); `heed_choice` refused to the player's SQL.
- A pin keeps a creature that walks to the far end an individual; unpinned, it goes back into the throng within its rule's hold and a pass.
- Contact: a throng member that strikes the player is in its `perceived` set with `since_ms` equal to the feed row's `at_ms` (the blow's tick).
- The kill switch: `heed_players` off empties `seen_throng` within a few ticks and the player perceives all eight again.

**What a client receives** (row-level security, a throng member named on no path, change only) is verify-client's `heed_rows.py` ([perception.md](../../verify-client/features/perception.md#heed-for-players)). The scale and cost of heed for players are not covered.
