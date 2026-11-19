# The fast lane's balanced frame

Built on `fast-lane-frame` (2026-11-19). It follows recommendation (a) of [why the fast lane disengages](FAST_LANE_WHY.md). **The fast lane stays off.** The world law `fast_lane_on` is still false, and nothing here turns it on. The new law `fast_frame` picks which prompt the lane uses when a trial turns it on: 2, the balanced frame (shipped), or 1, the first frame, kept so the two can be compared.

Three things change, and none of them is a guardrail:

- **The frame.** The four ways of answering a fight are shown alike, the danger is worded neutrally, and the lines that sold running away are gone.
- **The request.** It now carries the asker's own health and breath, and counts of what it saw when it was asked.
- **The battle fixture.** Fighters get personas: an even, seeded mix of martial, protective and timid sheets.

**No patch is checked, filtered or refused for what it does.** A bare `flee` ahead of the attack installs exactly as before: `mind/fast.rs` `change_of` is unchanged and tested for this. The owner's rule is that the model chooses, so guidance comes by example only.

## The frame, before and after

The fast system prompt is the frame, then the world's rules (`world_rules()`), then the graph grammar (`grammar()`). Frame 1 is byte for byte what the Nov 19 replicates sent (`prompts::fast_system_in`, unchanged). Frame 2 is `prompts::fast_balanced_in`.

**Before (frame 1).** The opening, as logged in the replicates:

> Something has just happened to you (see Why now). Your body goes on doing what your top level and your routines say while you think; what you answer changes them from the next moment on, not the moment that is passing. You may rewrite your `combat` branch, rewrite one of the routines listed under Your routines, switch your `combat` branch to one of them, or keep everything as it is.

The replies come in the order patch, routine, switch, keep. The world's combat text reads:

> A blow lands only if you are still within reach (about 2 m; a wolf's leap about 3.2) when its windup ends: stepping back or running as it winds up makes it miss, but whoever swings stands still meanwhile. You can outrun a person who keeps stopping to swing, not a wolf (a wolf catches the young, old, tired or surprised).

The grammar's repertoire example pairs seeing an enemy with flight:

> `{"if": {"sees": {"nearest": {"kind": "person", "relation": "enemy"}}}, "then": {"do": "flee", "target": {"nearest": {"kind": "person", "relation": "enemy"}}}}`

**After (frame 2).** The opening:

> Something has just happened to you (see Why now); How you are now gives your own health and breath and what you see at this moment. Your body goes on doing what your top level and your routines say while you think; what you answer changes them from the next moment on, not the moment that is passing. You may keep everything as it is, rewrite your `combat` branch, rewrite one of the routines listed under Your routines, or switch your `combat` branch to one of them. A `combat` branch can be written many ways, each as short as the others. Four of them, side by side; none is the right one, and which fits is yours to judge from who you are and what you perceive:
>
> - hold your ground: `{"first": [{"if": {"threatened": true}, "then": {"do": "block"}}, {"do": "strike", "target": "attacker"}], "label": "combat"}`
> - press: `{"first": [{"if": {"health_of": {"target": "attacker", "below": 50}}, "then": {"do": "strike", "target": "attacker", "run": true}}, {"do": "strike", "target": {"nearest": "person"}, "run": true}], "label": "combat"}`
> - make room and re-enter: `{"first": [{"if": {"any": [{"stamina": {"below": 25}}, {"count": {"of": "person", "within": 4, "at_least": 3}}]}, "then": {"do": "back_off", "target": "attacker", "distance": 5}}, {"do": "strike", "target": "attacker"}], "label": "combat"}`
> - break contact: `{"first": [{"if": {"health": {"below": 25}}, "then": {"do": "flee", "target": "attacker"}}, {"do": "strike", "target": "attacker"}], "label": "combat"}`

The replies come in the order keep, patch, routine, switch. The combat text keeps the same physics and drops the advice:

> A blow lands only if you are still within reach (about 2 m; a wolf's leap about 3.2) when its windup ends; whoever swings stands still meanwhile, and cannot swing again until it has recovered. A wolf runs faster than a person.

The grammar's second example hands a seen enemy to one of the character's own routines:

> `{"if": {"sees": {"nearest": {"kind": "person", "relation": "enemy"}}}, "then": {"routine": "facing an enemy"}}`

Both retreat examples have a condition that ends them and the fight underneath to return to. A guarded move stops when its condition stops holding, so the next child runs again; the grammar already said so.

**Scope.** The combat text and the repertoire example are changed for the fast prompt only. The rules (`skills.rhai` `combat_law`) and every other purpose's prompts are unchanged. That keeps the comparison to the fast lane, and it leaves think, deliberate and talk prompts byte-stable for other trials and for the providers' prefix caches.

The fast prompt matches the combat lines in the world's text as the shipped rules give them (`FAST_V1_COMBAT_LINES`). In a world whose combat words differ, the fast prompt keeps them as they are, and the mind logs this once. Both frames stay byte-stable across calls. The fake model still recognizes either frame as purpose `fast` (`fake_llm.py` `purpose_of`).

## The request: how one is, and what one sees

Both frames' user prompts end with a new section, after "What has just happened". That keeps the stable parts first for the providers' prefix caches. Under frame 1 the request also gains this section, so the trial compares the frames with the request held fixed.

```text
# How you are now
Your health: 62 (0-100).
Your breath (stamina): 40 (0-100).
In sight as you were asked: 7 people; of them 4 visibly in a hostile move (2 at you), 0 you count as friends or family, 1 you count as enemies.
```

| Field | From | Whose truth |
|---|---|---|
| Health | its own `vitals` row projected to now, as % of full (the scale of a graph's `health` condition) | self-perception |
| Breath | its own `vitals` stamina, projected by `living_rules::pools::level` (the scale of `stamina`) | self-perception |
| People, wolves in sight | the authority's new `fast_sight` row for this issue: `perception::sensed`, the one sight rule | its own sight when asked |
| Of them in a hostile move, and at it | `perception::visibly` (`combat` and `is("hostile")`), and `Visibly::at` | what it can see them doing |
| Friends or family, enemies | `brain::relation_ok` with `friend`/`family` and `enemy`: its own relationships, as a graph's `relation` reads them | its own feelings |

Nothing is counted from the world's truth: a person out of sight is not counted, and the verify case checks this with a stranger placed far away. A part that is not known is left out. If there is no sight row for this issue, the request has no sight line, and nothing is guessed. Why now is unchanged: the event as perceived, with no count.

### The `fast_sight` table

- **Shape.** One private row per character with a `fast_ask` row: `actor` (primary key), `issued_ms`, `people`, `fighting`, `at_me`, `friends`, `enemies`, `wolves`.
- **Writes.** It is written once per issue, in the same transaction as the `fast_ask` issue (`fast::pump` → `fast::sight`). The world's `fast_lane_rate` caps issues at 2 a second, so the sight gather (one `sensed` call around the asker) runs at most at that rate. It is removed with the request (`fast::forget`): when the row idles out, when the character is no longer served, on a death or a person's return.
- **Reads.** The mind service is the only subscriber, on a subscription of its own, `SELECT * FROM fast_sight`, as `fast_ask` has. A module without the table still starts; its requests then say nothing of what is in sight.
- **Growth.** Bounded by the characters with a live request.
- **Why a new table and not new columns on `fast_ask`.** Under the [automatic migrations](https://spacetimedb.com/docs/databases/automatic-migrations/) rules, adding a table is a safe change: "Adding new tables. Non-updated clients will not be able to see them". Adding a column is listed as potentially breaking: it must go at the end, it needs a default, and clients may need new bindings. On 2.14.1 the Spark also measured a column append rewriting the table and disconnecting clients.
- **Visibility.** Private, as [tables](https://spacetimedb.com/docs/tables/) describes: "Visible only to reducers and the database owner". It is grouped by access pattern: written and read once per issue, apart from `fast_ask`'s turn bookkeeping. [Subscriptions](https://spacetimedb.com/docs/clients/subscriptions/) allows several separate subscriptions on one connection.
- **Sources.** The docs were read 2026-11-19 at version 2.0.0; the trial server runs 2.14.1. The bindings were regenerated with `living/tools/generate_in_container.sh slop-trials-stdb`, with additions only: `fast_sight_table.rs`, `fast_sight_type.rs` and `mod.rs`.

## Personas for battle fighters

`battle_diag.py` gives every fighter, refills included, an authored sheet. Its fields are the ones a seed's residents carry (`seed.rs` `sheet`): narrative, values, goals, mood, traits (the eight `PERSON_TRAITS`), pastimes and calling. They are installed the way an authored resident's sheet is: the admin `set_background` with `{"sheet": …}` before the fighter's mind forms an identity. The mind's `Origin::Sheet` then installs the sheet as written, with no model call. `set_background` now also writes the sheet's traits into the body's genome (`seed::author_temperament`), as seeding does for an authored resident. The persona's traits are then the sheet's, not the ones drawn at spawn.

- **The sheets.** [battle_personas.json](../living/tools/battle_personas.json) holds three cohorts of three people each. They describe temperament only: no sheet says what to do in a fight. The verify case checks that no sheet mentions fleeing, backing off, retreating, striking, dodging or blocking.
- **The mix.** [battle_personas.py](../living/tools/battle_personas.py) `persona_mix(world_seed, n)` makes an even mix of the cohorts (34/33/33 at 100), shuffled by formation slot, with a sheet drawn per fighter, from the world seed alone. Refills draw from their own seeded stream, in spawn order. Every arm on one seed fights with the same people in the same places.
- **The record.** `diag-head.json` records each initial fighter's persona in `layout`. `diag-result.json` `persona_of` records every fighter's, refills included.
- **The old fixture.** `--no-personas` gives the fixture as it was ("(no persona yet)").

## How it is verified

- **Mind unit tests** (`mind/fast.rs`):
  - `the_balanced_frame_shows_four_ways_and_sells_none`: frame 2 has the four ways, each a legal patch, with retreats only under a condition. It has none of the three sold lines, which frame 1 still has, and lists keep first.
  - `the_request_says_how_one_is_and_what_one_sees`: the section's exact text. Nothing is said of an unknown part.
  - `no_patch_is_refused_for_retreating`: an unconditioned flee ahead of the attack, a bare flee, a bare back-off and a switch to a fightless routine are all installed.
  - `the_prompt_has_no_count_and_no_tactic`: now checked on both frames.
- **verify-minds `fast-frame`** (fake model): the persona mix, a sheet installed through `set_background` (persona and genome, no identity call), the v2 system text, the How you are now line equal to the issue's `fast_sight` row (friend counted, far stranger not), an unconditioned retreat installed, and `fast_frame` 1 giving the first frame.
- **Other surfaces.** verify-core `seen_again` and `fast_diag` check the authority's issue path with the sight gather. verify-llm `fast-route` and `fast-cap` check that the fake still recognizes both frames. verify-client checks that `fast_sight` is private.

## The trial

Results are in [the trial section below](#trial-results-2026-11-19).

- **Arms.** Arm B: the fast lane on with the shipped caps, real fast calls on DeepSeek V4.1 Flash, every other purpose on the fake model, `--keep-plans`. 100 fighters and 16 walkers on `island`, at the fixed site and formation the replicates used. Frame 1 against frame 2 (`--law fast_frame=1|2`), two runs each, interleaved v1 v2 v1 v2, five minutes each.
- **Held fixed.** The model, rules, seed, site, formation and persona mix are the same in every arm. The only difference is the frame.
- **Driver.** [flf_trial.py](../living/tools/flf_trial.py), started by [flf-all.sh](../living/tools/flf-all.sh) `--authorized`. Each run holds `~/slop-mq/battle.lock` and records the host's load.
- **Stops.** The spend watcher stops the whole trial at $2 of fast-call spend. A run also stops when more than 10% of its fast calls fail, or after two windows under 2 ticks a second. No run starts within 23:15–02:00 CET.
- **Report.** [flf_report.py](../living/tools/flf_report.py) gives the six exposure measures of `flb_report.py` per arm and per persona cohort, plus timed defence, the patch classification of [the WHY tables](FAST_LANE_WHY_TABLES.md) and cost.

## Trial results (2026-11-19)

**Frame 2 changed how the patches are written, not how the fighters fight.** Unconditioned retreats fell from 40% to 13% of installs. Retreats under a condition rose, and the condition the model wrote most often in both frames was its own breath. Contact, engagements, attacks and timed defence were all lower under frame 2. With two runs an arm, the attack, engagement and defence drops are consistent across runs, and the contact difference overlaps (v1 40.1%/44.4%, v2 33.5%/41.4%). Neither frame comes near the lane off: A100 in the replicates had 93.5% contact. **The fast lane stays off.**

**Setup.** Commit `6533b711` (code as `ba6fabec`) on base main `97858bbb`. Arm B at 100 fighters and 16 walkers on `island` world seed 7, site (406.5, 237.5), the replicates' formation. The persona mix (seed 7) was the same in every run, and so were the model (DeepSeek V4.1 Flash, thinking off), the shipped caps and `--keep-plans`. Runs were five minutes each, interleaved v1 v2 v1 v2, between 13:07 and 13:35 CET, with `battle.lock` held across all four. `flf_report.py` checked that the world seed, site, layout and persona layout were identical across the runs.

**Switches.** `fast_lane_on` on, `fast_frame` 1 or 2, shipped laws otherwise. Every purpose but `fast` was on the fake model (think 5 s, compile "keep", consolidation, talk), `LIVING_SKILL_TIMINGS` was unset, so on (the default; the harness does not set it), and `force_outcomes` was on (the shipped law).

**Host.** Every run held 60.0 ticks a second after warm-up. The 1-minute load averaged 2.8 and 2.8 in the v1 runs and 2.3 and 2.1 in the v2 runs (maximum 3.9). Every tick watch saw the clock advance: about 17,000 ticks a run, 26–27 checks each.

**Frame 1's text.** The v1 runs' fast system text has SHA-256 `f50c888e60b89ace4101e9c44748f64cd59f722c2b81b7f416923cb0b9d56aac`, byte for byte the replicates' (`journal/system/3e603a6ffd081a2feb3eb12409abe32b.txt`). Every fast request carried a persona and How you are now: 107 of 107 sampled in v1-1, and no "(no persona yet)" anywhere.

| Measure (fighters' observed time) | v1 · 2 runs | v2 · 2 runs |
|---|---:|---:|
| Attacks attempted / fighter-minute | 6.47 | 5.45 |
| Attacks / contact-minute | 15.3 | 14.6 |
| Time in contact | 42.2% | 37.4% |
| Engagements / fighter-minute | 2.15 | 1.23 |
| Retreats; re-engaged within 10 s | 1,332; 749 (56.2%) | 1,385; 654 (47.2%) |
| Damage taken / dealt per fighter-minute | 22.3 / 23.8 | 23.6 / 24.8 |
| Time away; idle or away | 60.9%; 88.4% | 65.8%; 89.3% |
| Timed defence, every sampled blow | 62.6% (4,027/6,435) | 55.6% (3,005/5,408) |
| Timed defence, bench windows; after the target's first patch | 59.3%; 70.1% | 53.0%; 54.3% |
| Deaths (run 1, run 2) | 11, 19 | 24, 13 |
| Fast calls; failed | 625; 0 | 502; 12 timeouts (2.4%) |
| Journal spend | $0.644 | $0.500 |

The installed patches, classified as in [the WHY tables](FAST_LANE_WHY_TABLES.md):

| Installed patches | v1 | v2 |
|---|---:|---:|
| Installs (switches) | 536 (43) | 424 (14) |
| Contains `flee` or `back_off` | 79.9% | 87.0% |
| An unconditioned retreat | 39.9% | 13.0% |
| An unconditioned retreat ahead of the first attack | 21.3% | 12.7% |
| A retreat ahead of the first attack, conditioned or not | 74.8% | 87.0% |
| Only conditioned retreats | 39.9% | 74.1% |
| Any attack or `close_in` | 67.2% | 81.8% |
| Explicit press | 7.3% | 0.2% |
| Retreat guards reading breath / health / a count | 80% / 27% / 0% | 76% / 56% / 18% |

Shares are of installs; switches have no graph to classify. The classifier reproduces the WHY tables on the archived B100 replicate: 60 unconditioned retreats (25%) and 23 explicit presses (10%), exactly as there. It counts fewer retreats overall (71% against 78%), because a switch to a routine is not opened. "Explicit press" is the WHY tables' narrow indicator: `close_in`, or an attack guarded on recovery, release, windup or the opponent's health. Frame 2's press example uses `health_of`, and almost no reply took it up.

**By persona** (v1 → v2; about 75–80 fighters per cohort and arm, refills included):

| Cohort | Attacks / min | Contact | Engagements / min | Re-engaged | Away; idle or away | Damage taken / dealt | Timed defence | Unconditioned retreat; ahead of the attack |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Martial | 8.06 → 6.57 | 45.9% → 38.9% | 2.68 → 1.44 | 53.9% → 53.5% | 51.4% → 62.7%; 85.9% → 87.5% | 24.3/28.0 → 27.1/29.3 | 67.2% → 57.8% | 18.1% → 1.3%; 0.5% → 1.3% |
| Protective | 7.47 → 5.95 | 45.7% → 38.0% | 2.52 → 1.27 | 70.3% → 43.5% | 61.3% → 64.3%; 87.3% → 88.1% | 26.0/27.2 → 26.0/27.2 | 59.6% → 51.0% | 42.2% → 2.6%; 14.8% → 1.9% |
| Timid | 3.89 → 3.96 | 35.0% → 35.6% | 1.26 → 0.99 | 38.6% → 43.7% | 70.0% → 70.1%; 91.9% → 92.2% | 16.6/16.3 → 18.3/18.5 | 59.8% → 58.8% | 73.7% → 43.4%; 70.2% → 43.4% |

The personas matter more than the frame. Timid fighters attack at half the martial rate in either frame, and they write most of the remaining unconditioned retreats. Martial and protective fighters almost stop writing unconditioned retreats under frame 2, yet they attack and engage less. Their guarded retreats fire often: breath falls with every move (about ten blows from fresh), and in a 100-fighter melee three people within 4 m is the usual case, not an exception. The "make room and re-enter" example's count guard appears in 18% of frame-2 retreat guards.

**What this does not establish.**
- Two five-minute runs an arm. The replicates ran ten minutes, and their fast installs came early: B100 had none after minute six.
- The request's new How you are now section and the personas were in both arms, so this trial says nothing about their effect. The arm closest to the replicates' B100 is v1 here: contact 43.3% there, 42.2% here, though at half the length and with personas.
- No lane-off run was made with personas.
- Persona traits also move the body's drives (curiosity, sociability, nurture: `brain.rs`), the same in both arms.
- The model's explanations were not read for causes.

**Cost.** $1.1441 of fast-call spend in total, by the journal. That is above the ~$0.6 estimate: the request is longer with the persona and the new section, and calls run about 60 a minute early in a run. It stayed under the $2 hard stop. The key copy was removed after the trial, and the scan found 0 files with key fragments. All four worlds were deleted (HTTP 404). Evidence: `~/slop-evidence/fast-lane-frame-20261119.tar.zst`.

**Next (for the coordinators).** A frame alone does not bring fighters back into contact. What the model writes is mostly "step back while out of breath", and with breath spent on every move, that guard fires all the time. The next comparisons are separate questions, not more framing: the same frames without How you are now (does a breath number invite breath guards?), and what a combat-plan patch may change at all (the replicates' design question).
