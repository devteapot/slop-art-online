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
- **The fighters' cheaper paths** (battle-cheap; docs/BATTLE_SCALE.md "The cheaper paths as built"):
  - **A move's check before it starts** is given only the fields its plan reads (`check_ctx_plan`; `act::checked`, `Reads`). The roll is drawn either way.
  - **The body's alarms** are kept per character until a fact `status_of` reads can change (`alarm_cells`; `brain::alarm_statuses`, `BodyFacts::next_change_ms`). The law's shared memo is keyed by those facts alone (`Scripts::status_reads`).
  - **Warmth** visits only what warms or shelters, in place (`common::chunk_warming`).
  - Each has a diagnostic `_check` law that also works the answer out the old way and counts differences.
- **The lazy scene** (scene-lazy; the `scene_lazy` law, on; `scene_lazy_check` a diagnostic):
  - A graph's scene is what the body senses (`perception::Sensing`): every creature within gathering range, nearest first, each tested for sight only when a reader comes to it.
  - The nearest pick (`Ev::first_seen`) and a creature looked up by id (`Ev::seen_by_id`: `visible_creature`, the `threatened` condition by facing) test only as far as their answer needs. Readers of the whole list (`Ev::creatures`: desires, `count`, `doing`, cues, noticing, the stranger filter) test every one.
  - Resources and the heard list are gathered when first asked for. The nearest pick reads the list in place, not a copy.
  - `perception::sensed` is `Sensing::all`, one implementation for both.
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
    - the blows O's lines count lie between the `fight_seen` rows naming O (read by polling, a lower bound) and the strikes the rules resolved (`skill_use` outcomes). When O is among every row read, they equal the strikes, landed and blocked;
    - V's fall is in O's lines once;
    - fewer lines than blows, at most one a window, the first within `witness_fold_ms` plus 100 ms of the first blow;
    - O is among most rows' onlookers, and neither of the two in a blow is;
    - D's own lines come at each blow, not folded;
    - with `witness_fold_ms` 0, O is told a first blow at once on its own line.
- **`cheap_check_ctx`, `cheap_alarms`, `cheap_warmth`** (about 1.5 minutes each; battle-cheap, the `check_ctx_plan` and `alarm_cells` laws, warmth in place):
  - 12 fighters on an open line, a campfire, a shelter and three dead among them, for 60 s, with the diagnostic laws `check_ctx_check`, `alarm_cells_check` and `warmth_check` on.
  - Each case asserts its own path from the `diag:` counts of its own window: many comparisons, none different. For the alarms, more answers kept than asked.
  - The counts are read from the server log's lines stamped after the case began.
- **`scene_lazy`** (about 2.5 minutes):
  - 12 fighters on an open line with `scene_lazy_check` on: 40 s with sight all round, 40 s by facing (`fov_on`), then 20 s with `scene_lazy` off.
  - Checks:
    - in both lazy windows a battle went on, and every lazy answer equalled the whole scene's (at least 200 compared, none differed);
    - by facing, creatures were looked up by id;
    - with the law off there were no lazy answers, and the battle went on.
  - Counts come from `diag:` lines stamped 2 s after profiling restarts (counts made while it was off are reported then).
- **The chronicle's repeat check read newest first** (battle-exact-2 E; the `chronicle_recent` law, on; `chronicle_recent_check` a diagnostic):
  - `common::chronicle` folds a line said again into its entry ("(×n)") when it is among the newest 40 entries of the last two minutes. It reads the last 1 s, 4 s, 16 s, then the whole two minutes, and stops at the first window holding 40 entries from before this tick.
  - Only entries before this tick count: a range read inside the tick's transaction gives this tick's rows apart from the committed ones (SpacetimeDB 2.14.1), so a narrow read short of 40 committed rows could pick one of them where the full read picks an older committed row. The first scene runs found exactly that (one of 68, then one of 460).
- **`chronicle_recent`** (about 2.5 minutes):
  - 16 people on an open line, each saying one of two short lines in turn; their graphs are reinstalled every 2 s (a say node speaks at most once per 45 s, an install clears it). `chronicle_recent_check` on: 60 s, then 30 s with `chronicle_recent` off.
  - Checks: lines were written and repeats folded; every newest-first read equalled the full read (at least 60 compared, none differed, no difference logged); both the narrow and the whole read were used; with the law off neither was, and lines were still written.
  - A difference's log line is saved beside the case's evidence (`<case>-differs.txt`).
- **Noticing read in place** (battle-exact-2 C1; the `notice_inplace` law, on; `notice_inplace_check` a diagnostic):
  - A look walks the chunks' structure lists in place (`common::for_structures_near`): those seen lately are re-marked, the rest marked and asked about nearest first, as the full pass does; the copied, sorted list is built only when something is new.
- **`notice_inplace`** (about 2 minutes):
  - 8 people walk back and forth along an open line while a builder puts up a shelter or a storage beside it every 3 s (each spot once: a tile beside a familiar one of its kind and owner is part of it and rightly not told). `notice_inplace_check` on: 45 s, then 20 s with `notice_inplace` off.
  - Checks: structures were put up and noticed; every in-place split equalled the full list's (at least 100 compared, none differed); the full list was built only for looks that found something new; with the law off there was no in-place look and new structures were still noticed.
- **A look checks only what is new since the last** (C2; the `notice_delta` law, on; `notice_delta_check` a diagnostic):
  - Each character a mind runs has a private `last_look` row: where its last look stood, its radius, the highest structure id in sight, when. A structure no newer than that and within that disc, seen again within 45 s, is passed over; every other is checked as `notice_inplace` checks it. Pruning spares structures within the last look's disc.
- **`notice_delta`** (about 2 minutes):
  - 8 people walk an open line among structures and four people's remains while a builder puts up a new one every 3 s; one walker is taken 120 m away for 50 s and brought back. `notice_delta_check` on: 50 s, then 20 s with `notice_delta` off.
  - Checks: structures put up and the remains noticed; looks incremental, passing over more structures than looks; every structure passed over familiar (at least 1,000 checked, none not); every walker has its `last_look` row; with the law off, nothing passed over and new structures still noticed.
  - A look comes about once a second, so a last look older than 45 s (a whole look) is a first look or one after a gap; the scene does not force one.
- `witness_wake` checks B's folded line holding the blow on V within `witness_fold_ms`; the `sight`, `fov` and facing duel scenes check who is told a fight (walls, facing) through the folded lines.

The rules tests `attention_cues_are_the_world_s_laws` (the laws' defaults and descriptions), `alarm_cells_give_the_law_s_answer_at_every_moment` (a cell's answer is the law's at every millisecond of five fighters' rows) and `fold::tests` (the line's words, counts and order) and the authority's `fold::tests` (each blow in exactly one window per onlooker) cover the rest offline. `profile_detail` (a diagnostic law) times the parts of each evaluation while profiling. The scale evidence is `living/tools/battle_diag.py` (docs/BATTLE_SCALE.md).

Not covered here: a missile's folded line (unit test only), a held-back wake delivered late in the scene (B's window may be free when A strikes; the bound holds either way), remains noticed once each in a long battle (`battle_diag.py`), and players' views (unchanged; verify-player `combat.py`).
