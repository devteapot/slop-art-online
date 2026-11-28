# The copy tables on a connected client (battle-views)

Since `battle-views-client` (2026-11-20; [docs/BATTLE_VIEWERS.md](../../../../docs/BATTLE_VIEWERS.md), "Rollout: one change set, one play-test window"). The authority can deliver a player's scene as rows of two public tables that row-level security (`viewer = :sender`) keeps to that player, instead of per-viewer views that re-run whole: `seen_body_copy` (the others' motion, behind `motion_tables_on`) and `seen_character_copy` (a mirror of the player's projections, behind `characters_table_on`). Both laws are value-only delivery laws in the `law_override` layer ([law-override.md](law-override.md)). The client follows them.

## How the client takes them

- **One switch, `net::perception_law`.** The perception set is a `net::Feed`: the tier state (`cue_transport_on` or `near_tier_on` on: the tiers and the cue tables; both off: the untiered views), `motion_table` and `characters_table`. `Feed::queries` builds it: the characters first (`seen_characters`, or `seen_character_copy`), then the streams, with `seen_body_copy` in place of the motion views (`seen_bodies`, or `seen_bodies_near` and `_far`). The motion cue table stays with the tiers. `seen_characters` is in this set, not the base set, so the table law can replace it.
- **Both table laws off** (on by default since `bv-defaults-on`; off by row): the set is the frame-views one plus `seen_characters` and `my_combat`, the queries main's client made before battle-views.
- **Make before break.** A new set is subscribed beside the old. Into a table, the reads move only once the table holds my scene (`tables_hold`: the authority moves a viewer's copies whole at its next frame, and fills the mirror whole; the views show them meanwhile). If that takes over 2 s, the log says `perception: the … set is in, waiting for my copies to reach the tables`. Out of a table (the kill switch empties it in one tick), the client keeps the table's rows for the reads until the views are in: deletes are not taken while it is leaving (`Copies::leaving_*`), or once the law's `law_override` row says `false` (`law_row_off`, for a delete that comes in the same frame as the row).
- **Readers.** Every read of characters goes through `net::characters`, `find_character` and `character_count`; bodies through `bodies`, `find_body`, `find_motion` and `motion_count`. `Copies` indexes `seen_body_copy` by `body` (it has no key; a change is the new row's insert, then the old one's delete) and the mirror by creature (`row.id`). `net::moving_of` turns a copy row into the `Moving` the views give.
- **The log.** `rules: cue_transport_on … near_tier_on … motion_tables_on … characters_table_on … fighter_tables_on … combat_feed_on … (script revision …, laws …)`; `perception: subscribing the tiered|untiered set (N queries; tables: motion M characters C fighters F combat_feed K; …)`; `perception: on the … set after N ms (tables: …; K others; … were in the old set, missing now […]; J characters, missing now […]; I fighters, missing now […]); overlays cleared …`. The fighter table and the combat feed share this switch: [combat-switches.md](combat-switches.md).
- **The seen log** (`LIVING_GAME_SEEN_LOG`) adds `tables` (`{"characters": C, "motion": M}`, the reads) and `characters` (the ids read) to each frame.
- **A body waits for its character row** before it is drawn (`live.rs`), since my own body now arrives in the base set a round trip before the characters.
- **Leaving and returning to sight** (`battle-spikes` / `battle-simplify`, 2026-11-28; `live.rs`, `anim::clip_root`). A body the authority stops sending fades out and is despawned; when that character returns to sight a new body is built with its current state ([body-return.md](body-return.md)). `anim::clip_root` reads each shared clip file once, which removed the 200 ms battle spikes; hidden-body reuse was removed after controls on both machines showed it within noise. With `LIVING_GAME_PERF=diag`, `bodies: in 2 s N left sight, M drawn new; …` lines count churn every 2 s. The battle bench (`living/tools/bench_battle.py`) measures battle frame times: [docs/TOOLING.md](../../../../docs/TOOLING.md#battle-frame-times-livingtoolsbench_battlepy).

## Drive

On an island world (`verify.py launch --seed island`), all explicit:

```sh
S=.agents/skills/verify-ui/scripts
$S/check.py --run "$R" battle-views        # the live switch, every combination, kill switch, reconnect, fresh client
$S/check.py --run "$R" battle-views-ui     # camera, talk and far with both table laws on
$S/check.py --run "$R" battle-views-cost   # kB/s and near ages, on against off (about 12 min)
```

**`battle-views`** starts one client (`LIVING_GAME_SEEN_LOG`) that waits at `sync:armed` while the driver sets laws over HTTP, 3 s apart, sampling `clock.tick` every ~20 ms. It first sets both table laws off (on by default since `bv-defaults-on`; a step that changes nothing is checked as kept), then steps through each table law alone and both, off and on again, in the tiered state, then with cues off (tiers only), with the tiers off (untiered, all four table combinations), and back with cues only, then tiers. For each call it checks:

- the call is accepted, the script revision unchanged, the in-place line names the law as delivery, and the tick never stands still 150 ms;
- when the set changes: the new set subscribed and the reads on it within 1.5 s; the switch line with nobody and no character missing; frame by frame, no frame without a creature or a character that was in the reads before the call and after the switch; the reads on the tables the laws name;
- when it does not (a frame law that keeps the tier state): the law read within a second and no subscribe;
- motion on: my copies all in `seen_body_copy`, none private (owner SQL); motion off, the kill switch: `seen_body_copy` empty within a second, my copies back in `motion_seen`/`motion_near`, none split;
- characters on: my mirror has a row per `projected` row; off: `seen_character_copy` empty within a second.

Then all eight (tier state × table laws) combinations are checked as run. With both table laws on, the client reconnects (`reconnect`): its first set reads both tables, with no view set before it. A fresh client subscribes only the table set. The four laws are restored from the world's own values (`law_values.own_laws`), else the shipped ones.

**`battle-views-ui`** sets both table laws on, runs `camera`, `talk` and `far` (their own checks, residents restored by them), checks that every client they started read both tables, and restores the laws.

**`battle-views-cost`** measures at two places (`BV_PLACES`): Brackenford's square among its residents, and a quiet open spot. At each, four drives (off, on, off, on). The client's connection goes through a byte-counting relay (`ByteRelay`, `LIVING_GAME_CLIENT_SERVER`, drive.py), and verify.py's player identity (the walker) stands 1.2 m away and walks a small octagon (a new `human_move` every 0.75 s for 40 s). It reports:

- **kB/s:** what the server sent the client during the walk, less its first second;
- **near ages:** for each fresh segment of the walker, the first frame whose reads hold it, less its `t_ms`. These are frame-quantized, alike in both arms, and leave out re-entries into sight (`walker_ages`);
- **context:** how long the walker was out of sight, the median count of others in the reads, and the frame rate.

The admin moves only the two players.

## Evidence

All under `.local/living/verify/RUN/ui/`:

- `battle-views.json`: per call, `t0`/`t1`, `effect_ms`, `laid_over_ms`, `gap_ms`, `ticks_per_s`, `empty_after_ms` (kill switch), `frames`/`kept`/`kept_characters`/`frames_missing*`, the authority's `copies` after it, the combinations, the reconnect and fresh subscriptions;
- `battle-views/client.log`, `battle-views.seen.jsonl`, `battle-views.drive.log`, `battle-views-fresh/`;
- `battle-views-ui.json` (each client and the tables it read), with the camera, talk and far evidence beside it;
- `battle-views-cost.json` (per place and arm; pooled kB/s and near p50/p90), `battle-views-cost-<place>-<k>-<on|off>/` and their `.seen.jsonl`.

## Not covered

- Scale: one client on the island; the 216-player costs are the authority's series (docs/BATTLE_VIEWERS.md).
- A real window, and a mind service (no resident answers in `talk`).
