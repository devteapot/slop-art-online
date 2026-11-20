# Law overrides on a connected client

Since `law-override-client` (2026-11-19, [docs/LAW_OVERRIDE.md](../../../../docs/LAW_OVERRIDE.md)). A world's own law values live in the public `law_override` table. A value-only law (`cue_transport_on`, `near_tier_on`, since battle-views `motion_tables_on` and `characters_table_on`, `gaze_on` and the five `cover_*` laws) changes there alone, with the `script` row and its revision untouched. Every other law still installs a new script revision.

## How the client takes them

- **The subscription.** `SELECT * FROM law_override` is in the base set (`PERCEIVED`, beside `script WHERE name = 'skills'`), so the first result after a connect or reconnect holds both.
- **Who notices.** The table's insert, update and delete callbacks bump a process-wide counter (`net::law_rows`). So does the base set being applied, since a world whose rows all went sends no delete.
- **When rules refresh.** `verbs::refresh_rules` runs in `Phase::Net`, after `net::pump` and before `net::perception_law`. It calls `Rules::refresh`:
  - a new script revision, a script that did not compile, or an in-place refusal: `Scripts::with_overrides(source, day_ms, overrides)`. The log says `rules: skill script revision N compiled (M skills, K law overrides)`;
  - the same revision with the rows changed: `Scripts::apply_overrides` in place. The log says `rules: law overrides laid over in place in X ms (changed [...]; delivery D cover C gaze G; script revision N unchanged)`.
- **`Rules::laws_key`** moves on each compile and on each in-place change of a law's value in force. Caches of law reads key on it, not on `revision`:
  - `perception_law`, the delivery laws that choose the set (`net::Feed`);
  - `heardmark`'s band distances;
  - `sightedge`'s `keep_seen_m`;
  - `live`'s walk/run split;
  - `facing`'s `walk_base`.
- **Per class:**
  - **delivery:** `perception_law` reads the four delivery laws again (the two frame laws and, since battle-views-client, the two table laws: [battle-views.md](battle-views.md)) and runs its make-before-break switch;
  - **gaze:** `gaze_enabled()` and `senses()` are read live from the refreshed script, so `sightedge` follows within a frame;
  - **cover:** the sight field follows the authority's `cover_law` row. It logs `sight field: cover policy … (the cover_law row)`.

## Drive

```sh
.agents/skills/verify-ui/scripts/check.py --run "$R" law-override    # an island world; explicit
```

**The scenario** starts one client (`LIVING_GAME_SEEN_LOG`) that waits at `sync:armed` and `sync:toggled` while the driver makes admin calls over HTTP. It samples the world's `clock.tick` every ~20 ms throughout. It does the following:

1. Sets each value-only law, 3 s apart: `cue_transport_on` off, `near_tier_on` off (to the untiered set), `near_tier_on` on (back to the tiered set), `cue_transport_on` on, `gaze_on` on and off, `cover_sight_on` on, `cover_brush_min_fill` to another value, and `cover_sight_on` off.
2. Sets `turn_rate` to 6.5 and back: two full installs.
3. Lets the client reconnect (`reconnect`), and sets both delivery laws off while it is offline.
4. Starts a fresh client with those rows present.
5. Restores every law it touched, from the `law_override` rows found at the start, or the shipped values.

**For each value-only law, it checks:**

- the call is accepted;
- the `script` revision is unchanged;
- the in-place line names the law and its class;
- the class's effect line comes within 1 s of the reply:
  - delivery: `rules: cue_transport_on …` or `perception: on the … set after`;
  - gaze: `sight edge: my senses from the authority (my_senses_v_2)` or `(my_senses)`;
  - cover: `sight field: cover policy …`;
- no compile on the client;
- the tick never stands still for 150 ms.

**For a set switch, it also checks:**

- the new set was subscribed beside the old;
- the switch line lists nobody missing;
- frame by frame, no frame lacks a creature that was in the reads just before the call and 1 s after the switch.

**For each `turn_rate` install, it checks:**

- the revision goes up by one;
- the client compiles it with the overrides;
- no perception subscribe follows.

**On the reconnect, it checks:**

- the laws went off while the client was offline;
- the base came back with the overrides;
- the first set chosen is the untiered one, with no tiered set before it.

**On the fresh client, it checks:**

- the compile names the overrides;
- only the untiered set was subscribed.

## Evidence

All under `.local/living/verify/RUN/ui/`:

- `law-override.json`, per call:
  - `t0` and `t1`, the wall time before and after the HTTP reply;
  - `rev_before` and `rev_after`;
  - `laid_over_ms` and `effect_ms`, measured from the reply;
  - `gap_ms`, the longest tick standstill in [t0 − 0.5 s, t1 + 1.5 s];
  - `ticks_per_s`;
  - for a switch, `frames`, `kept` and `frames_missing`.

  It also holds the quiet baseline gap, `reconnect` and `fresh`.
- `law-override/client.log`;
- `law-override.seen.jsonl`: each frame's reads, with `wall_ms`;
- `law-override.drive.log`;
- `law-override-fresh/`.

The sampler's resolution is one SQL round trip, about 30–35 ms on the laptop, so a quiet gap reads about 35 ms. A full install reads about 1.4 s on the island.
