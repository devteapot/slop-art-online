# The fighter table and the combat feed on a connected client (combat-switches)

Since `combat-switches` (2026-11-20; [docs/BATTLE_VIEWERS.md](../../../../docs/BATTLE_VIEWERS.md), addenda 4 and 5 and "Rollout"). The authority can deliver two more of a player's streams as rows that row-level security (`viewer = :sender`) keeps to that player, instead of per-viewer views:
- `seen_fighter_copy`: the fighters it perceives, behind `fighter_tables_on`. It is keyed, so a change is one update;
- `combat_feed`: an event table holding its combat feed, behind `combat_feed_on`. Each row has the id of its `combat_seen` row, and the client cache never keeps them.

Both laws are value-only delivery laws in the `law_override` layer ([law-override.md](law-override.md)), off by default until dev-box flips them. The client follows them, through the same switch as the copy tables ([battle-views.md](battle-views.md)).

## How the client takes them

- **Two more flags in `net::Feed`:** `fighter_table` and `combat_feed`, beside the tier state, `motion_table` and `characters_table`. That makes 32 sets, all built by `Feed::queries`:
  - the characters come first;
  - then the combat feed: `my_combat`, or `combat_feed`. `my_combat` moved from the base set to this set, so its law can replace it;
  - then the streams: `seen_fighter_copy` in place of the fighter views (`seen_fighters`, or `seen_fighters_near` and `_far`), and `seen_body_copy` in place of the motion views. The fighter cue table stays with the tiers.
- **Make before break, the fighters.** It works as for the copy tables:
  - going into the table, the reads move once it holds my scene (`tables_hold`): the authority moves a viewer's fighter copies whole at its next frame (`fighters_to_public`);
  - going out (the kill switch moves every copy back in one tick), its rows stay for the reads until the views are in. Deletes are not taken while leaving (`Copies::leaving_fighters`) or once the law's `law_override` row reads `false`.
  - `Copies::fighters` indexes the table by creature. A copy row ends that creature's fighter cue.
- **The combat feed.** There is nothing to hold, so both sources are read while both are in:
  - `net::take_combat` gives `combat::ingest` the `my_combat` rows in the cache, then every `combat_feed` row since the last frame (`Cues::combat`, at most 4,096);
  - `ingest` takes each id once (`Combat::seen_ids`). It forgets an id 60 s after the row expires, not when the cache drops it, so a switch back to `my_combat` cannot replay a death.
  - When a connection's first set takes the event table, `my_combat` is read once: subscribed, its rows copied out when applied (`combat feed: my_combat read once (N rows)`), then unsubscribed. A death screen's rows (kept two minutes) survive a reconnect.
- **A reconnect while dead joins no one** (`Net::died`, since combat-switches). Before, a reconnect reset `join_sent`, so the client joined a new stranger at once: the death screen went, and the join cleared the dead character's feed (`combat::clear_feed`). Now the flag is set when the character I play dies and cleared by "Arrive as a new stranger" (`Net::rejoin`); while it is set, a reconnect joins no one, and the death screen and its rows stay.
- **Readers.**
  - Fighters: `net::find_fighter` and `fighters`. Mine come from `my_fighter`, the others' from the views or the table, with a tier cue laid over either.
  - The combat feed: `take_combat` alone, its one reader being `ingest`.
  - The death screen, numbers, reactions and corpses come from `Combat`, whichever source.
- **The log.** It gives the six laws in this order:
  - `rules: cue_transport_on … near_tier_on … motion_tables_on … characters_table_on … fighter_tables_on … combat_feed_on …`;
  - the sets say `tables: motion M characters C fighters F combat_feed K;`;
  - the switch line lists those `missing now […]`: the others, the characters and the fighters.
- **The seen log** (`LIVING_GAME_SEEN_LOG`) adds `fighters` (the ids read) and `combat` (the feed ids `ingest` took since the last line) to each frame, and two keys to `tables`: `fighters` and `combat_feed`.
- **The dump** has `death`: the screen's `cause`, `place`, `lived` and `witnesses`, with the `killer_id` and `witness_ids` they were made from.

## Drive

On an island world (`verify.py launch --seed island`), all explicit:

```sh
S=.agents/skills/verify-ui/scripts
$S/check.py --run "$R" combat-switches        # the live switch with a fight beside me, kill switch, reconnect, fresh client
$S/check.py --run "$R" combat-switches-death  # the death screen from my_combat against combat_feed
$S/check.py --run "$R" combat-switches-ui     # camera, talk, far, death, bar, own, committed, move-off with both on
$S/check.py --run "$R" combat-switches-cost   # kB/s and near ages, each law on against off (about 25 min)
```

### `combat-switches`

The scene:
- a resident is held 1.6 m from me;
- verify.py's player identity (the striker) stands 0.9 m from the resident;
- the striker strikes the resident twice before the calls, and once before and once after each combat-feed call, so events are in flight across each switch.

The steps:
1. Both new laws off.
2. Each law on, off (the kill switch) and on again, tiered.
3. The copy-table laws off, then the frame laws off (untiered).
4. The same steps untiered, then with the copy tables on again.
5. The frame laws back.

For each call it checks the battle-views items: accepted, the revision kept, laid over in place, no freeze, the switch within 1.5 s, nobody missing in the line or in any frame (others, characters, fighters), and the reads on the named tables. Then:
- fighters on: my copies all public, none private;
- fighters off: `seen_fighter_copy` empty within a second, my copies private.

Across the run, the authority's `combat_seen` rows for me are polled by owner SQL (about every 60 ms). Every row polled while the client ran must have been taken, through each source, including those in flight across the combat-feed switches.

Then a reconnect with both laws on, which must choose that set first and read `my_combat` once, and a fresh client. The six laws are restored from `law_values.own_laws`, and the resident by `resident_fixture`. The resident must be alive at the end.

### `combat-switches-death`

The equality check is dev-box's death-screen check (verify-client `combat_feed.py`), made on the client.

The scene: two fresh players (`--token`), one with `combat_feed_on` off and one with it on. The stranger kills each with the death scenario's sharper free strike, beside a resident held still as a witness.

In each arm:
- the death screen (dump `01`) shows the authority's killer and witnesses. They come from `combat_seen` by owner SQL, in a `sync:truth` snapshot taken while dead (`scene.json` `snaps.truth`);
- the screen is the same after the law flips while dead (`02`), back (`03`) and across a reconnect while dead (`04`);
- the death row was taken from that arm's source (the seen log);
- with the law on, the reconnect read `my_combat` once, with the death's rows.

Across the two arms, the cause words, the killer and the shared witnesses' names are the same. `dmg_strike` and `cost_strike` are restored from the world's own values, else the shipped ones.

### `combat-switches-ui`

Sets both laws on and runs `camera`, `talk`, `far`, `death`, `bar`, `own`, `committed` and `move-off`, each with its own checks. Every client they started must read the fighter table and the feed. The two laws are restored afterwards.

### `combat-switches-cost`

`battle-views-cost`'s measurement (`delivery_cost`) for each law alone: two places, off, on, off, on, through the byte-counting relay. Every third move my own identity (the client's token) asks for a strike at no one, which the rules refuse: that refusal is a feed row for me alone, with no damage. The walker raises a guard once before the arms, if it has never fought, so it has a `fighter` row. It does not jump: a jump puts no row in an onlooker's feed, and one jump left a walker rooted for good (an authority gap; see the validation record). Each arm reports:
- `kB_per_s` and the near ages;
- `combat_rows` (taken in the window) and `fighters_median` (read).

## Evidence

All under `.local/living/verify/RUN/ui/`:
- `combat-switches.json`: per call, `t0`/`t1`, `effect_ms`, `laid_over_ms`, `gap_ms`, `empty_after_ms`, `frames`/`kept`, the authority's `fighters` copies; also `combinations`, `with_copy_tables`, `events` (`polled`, `taken`, `missing`, `by_source`, `across_switches`, the strikes), `reconnect` and `fresh`;
- `combat-switches/client.log`, `combat-switches.seen.jsonl`, `combat-switches.drive.log` and `combat-switches-fresh/`;
- `combat-switches-death.json`: per arm, the truth, the four dumps' `death`, the source and the one read. Also `combat-switches-death-{off,on}/` with their photographs and seen logs;
- `combat-switches-ui.json`;
- `combat-switches-cost.json`: per law, per place and arm, with `combat-switches-cost-<law>-<place>-<k>-<on|off>/`.

## Not covered

- Scale: one client. The battle-density privacy and cost come from the authority's series (docs/BATTLE_VIEWERS.md, addenda 4 and 5).
- The commitlog growth of `combat_feed` (dev-box's measurement before its default flips).
- A real window.
