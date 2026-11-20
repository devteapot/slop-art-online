# law-override-cover: law-override waits for cover in force (verify-ui)

Follows [2026-11-20-1536-combat-switches](2026-11-20-1536-combat-switches.md), where `law-override` passed 68 / 72 with all four failures in the cover laws.

- **Branch:** `law-override-cover`, from `origin/main` `c83ee5d18` (cover-stall merged), laptop.
- **Server:** the shared `sao-living_spacetimedb_1` (v2.14.1, 127.0.0.1:3300).
- **Builds:** the client and the module were built from this branch's tree in a private `CARGO_TARGET_DIR` (`~/.cache/law-override-cover-target`), through `build-slot` with `BUILD_SLOTS=1`. No owner session was open. The bindings were not regenerated: main already holds `cover_source`.
- **Runs:**
  - `ui-loc-1120-1949`: island, fresh, `law-override`;
  - `ui-loc2-1120-1956`: island, fresh, a second `law-override`;
  - `ui-locg-1120-1954`: Cullet, fresh, `gaze`.
  - All three databases were made by the `c83ee5d18` module and deleted after their runs; `verify.py cleanup` reported them deleted and the server answers 404 for each.
- **Evidence:** `.local/living/verify/<run>/ui/` (`checks.json`, `law-override.json`, `law-override/client.log`, `law-override.seen.jsonl`, `law-override.drive.log`, `law-override-fresh/`, `gaze/gaze-proof.json`). No model call was made.

## Change

This change is to the harness only. No table, reducer, view, subscription or UI control changed.

- **`check.py law-override`:**
  - After each cover call (`cover_sight_on` on, `cover_brush_min_fill`, `cover_sight_on` off), the driver polls `cover_law` (`id = 0`) every ~20 ms, for at most 10 s (`COVER_WAIT_S`), until the row reads the change in force.
  - The cover effect check now asks for `sight field: cover policy …` within 1 s of that read, not of the reply. If the row never reads in force, the check fails with "cover_law did not read … within 10 s of the reply" and the last row.
  - The next call waits at least 2 s after the read, so the brush edit lands after the switch-on's derivation has completed.
- **Recorded figures:**
  - `laid_over_ms` (the client's reaction to the override row) and `effect_ms` (from the reply) are measured as before;
  - new: `in_force_s`, `in_force_at`, `in_force_row` and `effect_after_in_force_ms`.
- **The tick-standstill check** keeps its 150 ms bound. For a cover call its window now runs to 1.5 s after the in-force read, so it spans the whole derivation. That makes it stricter, not looser.
- **A pre-check refuses an old world.** If `cover_law` reads off and there is no `cover_source` row, the world was made before cover-stall, and its switch-on would regenerate the land.
- **The check count stays 72.**
- **Docs:** `features/law-override.md` and `SKILL.md` say the scenario needs a world made at or after `c83ee5d1`, and describe the wait and the new fields.

## Results

**`law-override`: 72 / 72 on both fresh island worlds.**

| Call | Run | Laid over (ms) | Cover in force after (s) | Effect after in force (ms) | Effect after reply (ms) | Tick gap (ms) |
| --- | --- | --- | --- | --- | --- | --- |
| `cover_sight_on` true | 1949 | 5.1 | **1.702** | −6.9 | 1695.6 | 34.2 |
| `cover_sight_on` true | 1956 | 6.6 | **1.594** | −11.4 | 1582.9 | 30.4 |
| `cover_brush_min_fill` 0.5 | 1949 | 3.5 | 0.001 | 2.5 | 4.0 | 27.9 |
| `cover_brush_min_fill` 0.5 | 1956 | 7.5 | 0.001 | 6.9 | 8.2 | 29.8 |
| `cover_sight_on` false | 1949 | 5.4 | 0.005 | 1.5 | 6.4 | 30.5 |
| `cover_sight_on` false | 1956 | 8.7 | 0.001 | 7.9 | 9.3 | 32.4 |

Reading the table:
- **The switch-on:** cover read in force 1.59–1.70 s after the reply, against cover-stall's 1.9 s. The tick never stood still longer than 34 ms over the derivation, at 60 ticks a second.
- **The effect line** comes within a poll of the in-force read, so slightly negative figures mean the client's line led the driver's poll.
- **The brush edit** after the switch-on reached the client in 4.0 and 8.2 ms after the reply. The 2026-11-20 combat-switches runs had measured 2.44 s for the same edit sent during the derivation.

**Other steps on both runs:**
- delivery and gaze steps laid over in 0.4–18.8 ms, effects in 2.9–193.5 ms (gaze on: 176.9 and 193.5 ms, inside its 1 s bound);
- quiet gap 30.2 and 28.7 ms;
- both `turn_rate` installs compiled with the overrides;
- the reconnect took the untiered set first;
- the fresh client compiled with 6 overrides and subscribed the untiered set only.

**Afterwards:** the laws were restored, and `cover_derivation` read `done` on `ui-loc-1120-1949`.

**`gaze` (Cullet, `ui-locg-1120-1954`): 4 / 4.**
- the three stops have different authority-matched Shade fields;
- the wheel spin respects the limiter;
- the reconnect restores Far before the queued Near;
- gaze and cover hide the hedge contact at every stop.

## Not covered

- **Older worlds:** a world made before `c83ee5d1`. It is refused by the new pre-check, which was not driven.
- **Large lands:** a 4096 m land. cover-stall measured 11.2 s there, which is beyond this scenario's island-only use. `COVER_WAIT_S` would need raising for it.
- **A real window, and scale.**
