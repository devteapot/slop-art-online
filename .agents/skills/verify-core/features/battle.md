# Battle scale: familiarity, novelty, bystanders' wakes

What lets a dense battle of minded characters keep its tick (docs/BATTLE_SCALE.md, fixes 1–3, `battle-scale`). Nothing a character sees or is told changes; when the work is done does.

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

The rules test `attention_cues_are_the_world_s_laws` checks the law's default and description. The scale evidence is `living/tools/battle_diag.py` (docs/BATTLE_SCALE.md).

Not covered here: a held-back wake delivered late in the scene (B's window may be free when A strikes; the bound holds either way), remains noticed once each in a long battle (`battle_diag.py`), and players' views (unchanged; verify-player `combat.py`).
