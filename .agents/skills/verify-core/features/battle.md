# Battle scale: familiarity, novelty, bystanders' wakes, folded fight lines

What lets a dense battle of minded characters keep its tick (docs/BATTLE_SCALE.md: fixes 1–3, `battle-scale`; fix 4, `battle-fold`). For fixes 1–3, nothing a character sees or is told changes, only when the work is done. Fix 4 changes how onlookers are told: one folded line a window holding every blow they saw, more than the fight's first blow they were told before.

## What it does (user POV)

- **Familiarity forgets by age only, never what is in view** (fix 1; `brain.rs`):
  - `FAMILIAR_LIMIT` is 2,048 rows a character, not 256. Over it, `prune_familiar` removes the oldest rows by `last_ms`.
  - It never removes a row touched within `FAMILIAR_KEEP_MS` (60 s), nor one whose thing is in the character's seen set within `SEEN_MS` (90 s).
  - The check runs every 64 new rows of that character.
  - The recently-seen fast path is a per-character set (`SEEN`, thread-local) sized to what it saw. It used to be a 96-entry list on `mind_state`, which thrashed and was rewritten at every evaluation; the row's `seen` stays empty now.
- **Novelty once a second** (fix 2): `noticed()` runs at most once per `NOTICE_MS` (900 ms, a little under the 1 Hz slot) per character, not at every woken or combat-cadence evaluation. Cues keep their own interval (`cue_check_s`). A crowd's first sights are told a few to a line (`FIRST_SIGHTS_PER_LINE`) at each look.
- **Bystanders' wakes** (fix 3; the `witness_wake_ms` law, default 500; 0 means woken by each sight, as before):
  - A witnessed event's percept is written at once and in full to every onlooker (`perceive::witnessed`, `witnessed_shot` → `percept_seen`).
  - A party to it (its subject, or the one it was done to or aimed at) is woken at once.
  - A bystander is woken at most once per `witness_wake_ms` (`common::wake_bystander`). A wake held back is delivered when its window ends (`due_bystander_wakes`, each tick before the wakes).
  - A remains noticed is a bystander's sight too.
- **Folded fight lines** (fix 4; `fold.rs`, `living_rules::fold`; the `witness_fold_ms` law, default 2,000; 0 means each fight's first blow told at once on its own line, as before):
  - Each blow (landed, blocked, dodged, missed) is written once to a private `fight_seen` row with everyone who could see it under `witnessed`'s sight test (facing and walls included), the two in it excepted.
  - Each onlooker gets one `fight` line per window, ending at its own phase: who struck whom in the order each pair was first seen, how many blows and how each ended, and who fell ("A stranger (#412) attacked Grim: 3 blows (2 landed, 1 blocked), and Grim fell."). A mind's line anchors each one it cannot name by its scene id (a far figure by its handle); a player's reads as the screen shows it.
  - A blow at or by the onlooker is not folded: its own lines come at once, as before. A death is still told at once on its own line too.
  - A fight's first landed blow wakes its onlookers as bystanders when it lands (as its line did); the folded line wakes no one.
  - Pending blows are rows, not module memory (SpacetimeDB keeps no module state between calls); a row goes once every onlooker's window holding it is told.
- **Remains in sight** (`brain.rs`): a scene's structures are gathered only when an evaluation reads one (`Ev::structures`), so a fighter's 15 Hz evaluation does not copy every remains in sight; noticing checks each structure's id against the seen set and copies their details only when one is new.

## Driving it

On a launched default-seed run (`scenes.py <case> --run "$R"`):

- **`familiar_dense`** (about 5 minutes):
  - O stands among about 360 people (well over the old cap), placed within 7 m and standing still, for 150 s.
  - Checks: more than 256 familiarity rows; one row per person; each told as a first sight exactly once (no row forgotten while in view and made again).
- **`notice_rate`** (about 30 s):
  - Two fights among ten minded people.
  - Checks: during a 12 s profiled window, the noticing passes a second (the `diag:` counts) stay at most one per 0.9 s for each minded character, while evaluations run at least 1.3 times as often.
- **`witness_wake`** (about 1 minute):
  - B stands beside V and has appraised V; B's graph waves at V once V is hurt; V's graph waves once hurt.
  - Five decoy fights start in B's sight, then A strikes V.
  - Checks:
    - every fight is told to B at once, its line about A and V in the same transaction as V's hurt;
    - wakes were held back (`wake:deferred`);
    - B waves within `witness_wake_ms` plus 100 ms of the blow;
    - V, a party, within 100 ms.

- **`witness_fold`** (about 1.5 minutes):
  - O stands between two fights: A, with a spear, strikes V until V falls; C strikes D, who blocks.
  - Checks:
    - the blows O's lines count, landed and blocked, equal the strikes the rules resolved (`skill_use` outcomes; V's own lines go with its death);
    - V's fall is in O's lines once;
    - fewer lines than blows, at most one a window, the first within `witness_fold_ms` plus 100 ms of the first blow;
    - O is among every `fight_seen` row's onlookers, and neither of the two in a blow is;
    - D's own lines come at each blow, not folded;
    - with `witness_fold_ms` 0, O is told a first blow at once on its own line.
- `witness_wake` checks B's folded line holding the blow on V within `witness_fold_ms`; the `sight`, `fov` and facing duel scenes check who is told a fight (walls, facing) through the folded lines.

The rules tests `attention_cues_are_the_world_s_laws` (the laws' defaults and descriptions) and `fold::tests` (the line's words, counts and order) and the authority's `fold::tests` (each blow in exactly one window per onlooker) cover the rest offline. `profile_detail` (a diagnostic law) times the parts of each evaluation while profiling. The scale evidence is `living/tools/battle_diag.py` (docs/BATTLE_SCALE.md).

Not covered here: a missile's folded line (unit test only), a held-back wake delivered late in the scene (B's window may be free when A strikes; the bound holds either way), remains noticed once each in a long battle (`battle_diag.py`), and players' views (unchanged; verify-player `combat.py`).
