# First sight asks for a thought (design, 2026-11-12; not built)

Status: **design only, for the owner's decision.** Nothing is built and no paid call was made. Code is read from main `ef9c3ae5`. The cost figures come from recorded trial runs, counted read-only (§4).

**The gap.** In strangers stage 2 and 2b (docs/TRIALS.md), a resident's first sight of someone it cannot place arrives in its experiences as a first-sight line, but it never asks for a thought.
- Ingrid Morrow saw the newcomer from 1.8–2.7 m on the Strand in all four st2b arms, each time with "For the first time you see a stranger, 7 tiles east, goto → (490,779)."
- None of her 3–7 thoughts after the join mentioned the newcomer, and she told no one.
- Aldous Quill thought 3–6 times after the join in stage 2, and the newcomer was in none of those prompts.
- Re-scored with the walk counted as in range (st2b analysis, main `ef9c3ae5`), 18–24 residents were in range per arm and 78–100% of them were unaware. Ingrid was unaware in every arm.
- The cue arm (st2b, `cues_on`) did not fill the gap. Minds wrote 128 cues on people and debts they already knew. 9 cues were on `who: "unknown"`, and none fired on the newcomer.

A first sight has salience 0.45 (`brain.rs` `noticed`). Only a percept at 0.6 or more wakes the body's graph (`perceive.rs` `percept`), and no percept asks the mind to think by its salience alone. A thought is asked for only by fixed callers (`request_deliberation`): being attacked, offers, the body's alarms, a plan ending or failing, a quiet moment, a cue.

**The proposal.** A first sight of someone the character cannot place asks for one thought, bounded by the existing throttle. This is a perception fact, the same as noticing an unfamiliar face. What the character does about it is its own choice: it may speak, watch, tell someone, or be curious inside without showing it.

## 0. What the owner rejected, and why

**Where it came from.** Branch `exp-arrive`, commit `fb622e1c` ("Arrivals: the arrive trial, arrive_report.py and three newcomer laws (all off by default)"). The laws were measured in ar2 (docs/TRIALS.md, "Arrival batch ar2"). `arrive-2` (`764d4ed1`, "remove the newcomer laws (rejected)"; merged as `760a78b7`) brought only the trial tooling to main.

**The owner's words** (docs/TRIALS.md, ar2): "I don't really like the fact that this has been encoded as a world rule. It should be something emergent from the personality and role of NPCs." The laws "were not merged, not even switched off".

**The laws**, as `fb622e1c`'s `skills.rhai` defined them:

| Law | Shipped | Text in `skills.rhai` |
|---|---|---|
| (the category) | — | "A newcomer to someone is a person who came into the world (joined, arrived, was born) and was first seen by them more than 10 s after they themselves came into it, and who is not of their community." |
| `newcomer_salience` | 0 | "the first sight of a newcomer within `newcomer_home_m` of one's home door has salience 0.45 + this x the mean of one's curiosity and sociability (as a share; at most 0.95), a crowd does not hide it, and a sight salient enough to wake one (0.6) asks for a thought." Its line: "For the first time you see {who}, {place}, near your home." |
| `newcomer_home_m` | 60 | "Within this many metres of one's home door one is near home." |
| `newcomer_scene_min` | 0 | "what one perceives marks a newcomer first seen within this many minutes as new to you." |
| `newcomer_drive_s` | 0 | "a calm person who has no feelings about a newcomer within `newcomer_near_m` wonders about them this many seconds after first seeing them (x 1.5 for the least curious and sociable, x 0.5 for the most), once every 10 minutes." Its feeling: "You feel something: You find yourself wondering about {who}, … someone you do not know, about here since you first saw them … ago." Constants: wondered about again at most every 10 min, at most one wondering a minute, never after 30 min. |
| `newcomer_near_m` | 12 | "How near a newcomer must be for that wondering, metres." |

ar2 armed these laws as follows: `notice` set `newcomer_salience` 0.5, `known` set `newcomer_scene_min` 30, `wonder` set `newcomer_drive_s` 90, and `all` set all three.

## 1. The rule

**In three lines:**
1. When a character with a mind first sees a person it cannot place, close enough to make them out, the look's first-sight line also asks its mind for one thought.
2. The reason given is that first-sight line, word for word. Nothing is added to the scene, the line or the prompt.
3. The existing throttle bounds it (`think_min_s`, merging into a pending request), plus one gap a character. A sleeper gets no request.

### "Can't place"

The test is the one the far label and the cue matcher already use, read for each person in the look:
- **known by name:** `perception::knows_name(me, them)` is true. That covers oneself, parents, children, the other parent of one's children, one's community, and anyone who told one their name (`acquaintance`). Players' clients read the same sources through `my_known_names` (owner-known).
- **far:** `perception::regard(me, them).far` is true. The `perceived_of` law marks someone too far away to make out, for example past Cullet's `known_within` of 24 m.

"Can't place" means not known by name, and not far. A far figure can't be made out, so it is not yet a sighting at all. `noticed` already tells no first sight of a far figure and writes no `familiar` row for one; it looks again every 5 s (`far_wait`). When the figure comes within making-out distance, its first sight is told then, and then it asks.

**No new test is needed.** `noticed` already builds each first-sight part from `common::label_for` and records `named = who == ch.name`. The label is the name exactly when `knows_name` holds and the person is not far. An unnamed part is "a stranger", "an old stranger", "a child" or "a baby". The rule fires when a look's first sights include at least one unnamed part.

This is not the `stranger_by_name` filter. That filter is `!knows_name` alone, so it also matches far figures. The rule excludes them, as cues on `who: "unknown"` do (`brain.rs` `cues`: `if far || (c.who == "unknown" && named) { continue }`).

### "First sight"

A first sight is the existing bookkeeping, unchanged: no `familiar` row for `(observer, FAM_CREATURE | id)` (`by_actor_thing`) when the person is made out. The same look writes the row (`familiarity`).

**When it re-arms:**
- **Never for the same pair while the row lasts.** "You see X again after a long time" (no `familiar` touch for more than a game day, salience 0.25) is recognition of someone familiar, not a first sight. It does not ask.
- **After forgetting.** The body keeps at most 256 `familiar` rows (`FAMILIAR_LIMIT`) and drops the oldest by `last_ms`. Someone dropped and later seen again is a first sight again, so it asks again. This happens only to a character that has seen more than 256 creatures since, which in practice means a city. The gap below bounds it there.
- **After the person becomes placeable:** someone who told you their name is named in later lines, so they never ask.
- **A new identity** (a new character after a death) is a new id with no rows, so it is a first sight to everyone.

### The request

- **The reason** is `first_sight_text` over the look's unnamed parts only, in the line's own words: "For the first time you see a stranger, 7 tiles east, goto → (490,779)." Several in one look give one reason: "For the first time you see a stranger, 9 tiles west, wait; and a child, 3 tiles north."
- **The experience row is unchanged:** one line, all first sights of the look, at salience 0.45, with named people included.
- **What the reason must not hold:** no advice, no "worth a thought", no "new to you", no "newcomer", "visitor", "arrival" or role word, and no place word ("near your home"). It is what was perceived. A unit test pins the reason to `first_sight_text` output, as `cue_examples_name_no_one` does for cues.
- **The prompt** gains nothing. The request's scene is the scene of that moment (`perceive::request` builds `scene_json`), so the person is in it as `who: "a stranger"`, with their position and what they are visibly doing.
- **The rethink gate** (`LIVING_RETHINK`, off by default): the reason is not in `rethink.json`'s `urgent` list, so the gate judges it like any other. Its `unhandled` question already counts "a new person" as a reason to think. The reason is deliberately not made urgent.

### Throttle

The rule calls `perceive::ask_to_think`, the path cues use, and adds one gap and one retry.

1. **`think_min_s`** (people 20 s, `species.json`). If the mind thought within that time and nothing is pending, the request is refused.
2. **Merge.** If a deliberation is already pending, the reason merges into it (`reasons::add`). This adds no deliberation.
3. **Retry while owed.** A refused request is *owed*. It is tried again at the character's next look, while all three hold:
   - the person is still in sight and still can't be placed;
   - no deliberation has been made whose scene held them;
   - less than 60 s has passed.

   This is the cue rule's retry ("tried again at the next check"), plus an end condition: the goal is one thought with them in view, whatever asked for it. A thought for any reason with the stranger in its scene settles the debt. The owed set is thread-local, like `CUE_HELD`. A module update loses it, and the line itself stays durable.
4. **The gap: `first_sight_gap_s`** (default 300 s, 0–3,600). A character's first sights ask for a thought at most once in this time. First sights inside the gap merge into a pending request if one exists, and are otherwise dropped, not owed. In Cullet and the hamlet the gap barely binds (§4). It exists for a city, where without it a resident walking a busy street could be asked every 20 s.
5. **The graph's `think` node** throttle (45 s after a decision, then once per 90 s, `brain.rs`) is separate and unchanged. A routine that reacts to the same sight merges into the same pending request.

### Controllers

- **A mind's character (`ai`):** as above.
- **A player's character:** `noticed` returns at once for a played character (`if !self.me.ai`). So no first-sight line is written for it, and it has no mind to ask. The player sees the same fact on screen: the person in `seen_characters` with an empty `name` and `label` "a stranger". The rule changes nothing for players, and the stranger they *are* to residents is exactly what makes residents think. The brief that asked for this design said players already see the first-sight line. They do not: they see the person, not the line (checked in st2b: the newcomer, id 65, had 27 experiences and no first-sight line).
- **Player memory** (`LIVING_PLAYER_MEMORY`, `lived.rs`) reads what the player lived, not first sights. Unchanged.
- **Takeover.** When a player leaves and the minds take the character, `familiar` rows were not written while it was played. Its first look then makes first sights of everyone in view. The takeover itself already asks for a thought (`presence.rs`: "A quiet moment to take stock…", counted as having just thought). Those first sights are refused by `think_min_s`, owed, and then settled by that takeover thought, whose scene holds them. So the takeover adds no second thought.
- **Animals** follow the same path when they see one of their own kind they can't place. `request`'s existing gates apply: animals think only near people, and `think_min_s` is 240 s. The trials measure people only.

### Sleepers

A sleeper gets no request. Sleeping bodies aren't watching.
- **Today on main**, a sleeper's look still writes first-sight lines and `familiar` rows. There is no sleep gate in `request` (bi1: 30–34% of deliberations came from sleepers). `fix-sleep-thinking` (`perceive::asleep`, `Slumber`, `request_waking` with `Wake::{Attack, Body, Cry}`) is not on main.
- **With the law on**, a sleeper's look makes no first sight of someone it can't place: no line, no `familiar` row, no request. It is treated like a far figure, not yet seen. The first look after waking makes the first sight, and that look asks. So the gap does not swallow a real first look, and a sleeper does not "remember" a face it never saw.
- **With `fix-sleep-thinking` merged**, the check is `perceive::asleep`. The request is not a `Wake` reason, so it never wakes a sleeper. It is also not stored in `Slumber`, because the sight did not happen.
- **Without that branch**, the check is the body's activity being `sleep`.
- **Not covered here:** whether sleepers perceive anything else (scenes, other lines). That is a perception question outside this rule.

## 2. The switch

A world law beside `cues_on` in `skills.rhai` `laws()`, `script.rs` `Laws`, `laws_about` and the law tables (this page; docs/ATTENTION.md "Laws" gains a row pointing here):

| Law | Default | Meaning (`laws_about`, written for a mind) |
|---|---|---|
| `first_sight_thinks` | `false` | On: "seeing someone you cannot place for the first time brings you to think". Off: "one thinks when something happens to one; a first sight is noticed, not thought over". Off, nothing changes, the sleeper rule of §1 included. |
| `first_sight_gap_s` | `300` (0–3,600) | "a first sight brings one to think at most once in N s" |

Both are switched at runtime by `set_world_law` and read back from `world_law`, as the trial runner's laws guard already does for `stranger_by_name` and `cues_on`.

**With `cues_on`.** The two are independent.
- `cues()` runs first in `noticed`. A cue on `who: "unknown"` that matches the same person in the same look fires first. Its `ask_to_think` creates the pending request, and the first-sight reason merges into it: one thought with two reason lines, the mind's own "you watch for this (…)" and the plain first sight.
- That thought has the person in its scene, so the first sight is settled.
- The cue gap (`cue_gap_s`) and the first-sight gap are kept apart, so neither law changes the other's counts.
- With cues off and this on, the stranger still asks once. That is the st2b gap the cues did not fill.

**With `stranger_by_name`.** Also independent.
- The filter decides what a *routine* matches. This rule decides when the *mind* is asked.
- Under both, a routine `sees {relation: "stranger"}` can react in the same frame, and a `think` node in it merges into the same request.
- The filter also matches far figures and this rule does not. A routine may walk toward a far figure before the mind is asked about them. That is how it is today.

## 3. How it differs from the rejected newcomer laws

| Point | Rejected (`fb622e1c`) | This rule |
|---|---|---|
| **Salience scaled by traits** | "salience 0.45 + this x the mean of one's curiosity and sociability … a sight salient enough to wake one (0.6) asks for a thought" | Salience stays 0.45 for everyone. Traits are not read. The request does not pass through salience: everyone with eyes and a mind is asked once, and what they do with it is their personality's. |
| **Timed drive or decay** | `newcomer_drive_s`: "wonders about them this many seconds after first seeing them (x 1.5 for the least curious and sociable, x 0.5 for the most), once every 10 minutes"; "You find yourself wondering about …"; nobody after 30 min | No timer and no feeling line. One request at the moment of sight, retried only while it is owed (60 s, in sight). It never comes back on its own. |
| **"Near home" or place rule** | "within `newcomer_home_m` of one's home door"; the line "…, near your home." | No place is read. The rule applies anywhere one can make someone out. The line is the existing one. |
| **Newcomer or stranger role** | "a person who came into the world (joined, arrived, was born) and was first seen by them more than 10 s after they themselves came into it, and who is not of their community"; `newcomer_scene_min` marks them "new to you" | No category, and arrival time is not read. Anyone one can't place: the newcomer, another settlement's fisher never seen before, a visitor's child. The scene is unchanged (no "new to you"; ar2 `known` showed that mark changes nothing). |
| **Prescribing what to do** | "wonders about", and a line that frames the sight | The reason is the perception line verbatim. The prompt says nothing new. A thought may end in doing nothing ("curious inside, but they don't show it"). |

**Where it is close, said plainly.**
- **It is still a world law.** The owner's objection was to "encoded as a world rule", and this is one. The case for it is that it is a *perception* law of the same kind as "being attacked asks for a thought": general, the same for every observer and every unplaced person. It says nothing about strangers' importance, a resident's duty or what to do. Whether that difference is enough is the owner's call.
- **Its mechanism is close to ar2 `notice`.** With `newcomer_salience` 0.5, anyone whose curiosity and sociability averaged 30 or more crossed 0.6, which is nearly everyone. So `notice` was in effect "a first sight near home asks for a thought". What `notice` did is the best existing forecast of this rule:
  - residents asked to think 7–10 of 11;
  - contact share 0.30–0.82, against control's 0–0.12;
  - `converge_60s` 2–6;
  - 34 of 63 lines to the newcomer out of earshot;
  - no change in false replies, repeated lines or cost per resident-hour.

  The differences: this rule asks within making-out distance only (Cullet 24 m; first-sight distance median 16–20 tiles in st2/st2b), where `notice` asked at 26–48 tiles, and it has no trait scaling.
- **The crowding risk is real.** In Cullet one arrival is seen by 24–38 residents, 4–10 of them within the same 10 s (§4). The target spread's "out of shape" mark, "5 or more askers in a run, the newcomer-law pattern from ar2", may be hit. The trial in §5 measures it first.

## 4. Cost at Cullet in a crowd

**Basis.** A read-only count over recorded runs, using the would-fire rule of §1 over every first-sight line actually written. No new run.
- **Runs:** st2 (3 runs) and st2b (4 runs). Each is Cullet, 63 thinkers, 20 minutes (21 resident-hours), the newcomer joining at 09:30, on a far-label build, so far figures already get no first-sight line.
- **Hamlet:** ar2 control (4 runs, 11 thinkers, 14 minutes), as the "several settlements" case. That build is from before far-label, so parts beyond 24 tiles were dropped as a stand-in.
- **The throttle model,** per firing:
  - *asleep*: the census activity was `sleep`;
  - *refused*: a deliberation reply within 20 s before;
  - *merged*: a deliberation came anyway within 30 s after;
  - *gap*: within the gap of an earlier added one;
  - otherwise *added*. This is an upper bound: an added request may only bring forward a thought that would have come.
- **Script:** `would_fire.py` and `bursts.py` (session scratch; not committed: they read the trial directories `~/slop-trials2b/.local/living/trials/st2b`, `~/slop-stage2/.local/living/trials/st2` and `~/dev/slop-runs-arrive/.local/living/trials/ar2`).

| Runs | First-sight lines | Would fire | Distinct observers | Asleep / refused / merged / gap | **Added** | Deliberations in run | Added share |
|---|---:|---:|---:|---|---:|---:|---:|
| st2 C, L, LS | 1,380–1,554 | 24–27 | 24–27 | 0 / 3–6 / 4–6 / 0 | **16–17** | 384–390 | +4.1–4.4% |
| st2b C, L, LS, LS+cues | 1,307–1,575 | 24–38 | 24–38 | 0 / 4–6 / 1–7 / 0 | **15–26** | 383–485 | +3.9–5.4% |
| ar2 hamlet control (gap 60 s) | 127–134 | 12–28 | 9–12 | 0–4 / 1–5 / 1–7 / 0–7 | **9–14** | 55–67 | +15–21% |
| ar2 hamlet control (gap 300 s) | | | | gap 1–8 | **8–13** | | +13–20% |

**In Cullet the rule fires once per resident per arrival.** Every firing in all 7 runs was a distinct observer seeing the newcomer, the only person in Cullet nobody can place.
- **Rates:** 24–38 firings per arrival, or 1.1–1.8 per resident-hour over a 20-minute run. They are concentrated in the minutes after the join.
- **After the throttle:** 15–26 added deliberations, 0.7–1.2 per resident-hour, against a base of 18.2–23.1. Nobody was asleep at 09:30.
- **The gap** does not bind in Cullet, with one stranger per run.

**The crowd case** (the yard at 09:30, the Strand walk past the Fish Steps).
- The throttle is per observer, so it does not spread a crowd's requests: everyone who sees the arrival is asked within seconds.
- **Measured:** 4–10 firings within 10 s and 7–18 within 60 s, per run.
- **The limit** is the cast: one arrival in front of all 63 residents gives at most 63 requests, and about 40 added after the throttle, by the 60–70% added share above.
- **Machine cost:** the authority writes one `deliberation` row per request, an existing path. The mind service runs them at `LIVING_CONCURRENCY` 64, which holds.
- **Behaviour cost:** convergence, as in `notice` (§3).

**Several settlements** (ar2's hamlet as the stand-in).
- Other settlements' people are first sights too: 12–28 firings per 14 minutes for 11 thinkers, and up to 6 per observer.
- After the throttle that is 3.5–5.4 added per resident-hour, about +15–21%.
- It is front-loaded. Once per pair, the rate falls as people become familiar. Hours of evidence do not exist.

**A city** (no evidence; the bound). Where most people one passes can't be placed and the 256-row `familiar` cap forgets them, the gap is the limit: at most 3,600 / `first_sight_gap_s` added per resident-hour.
- At 300 s that is 12 an hour, about +60% on 18 an hour.
- At 60 s it would be 60 an hour, which is why the default is 300 s.

**Dollars.** An all-in cost per deliberation, including the talk and consolidation that come with it, from st2 and st2b: $2.47–3.08 a run over 383–485 deliberations is **$0.0063–0.0065**. ar2 `notice` measured no rise in cost per resident-hour ($0.159 against control's $0.164), so the all-in rate is a fair upper estimate.

| Case | Added per resident-hour | Added $ per resident-hour | At bi1's $0.13 | After the sleeper fix (about −12% deliberations, so about $0.115) |
|---|---:|---:|---:|---:|
| Cullet, one arrival per 20 min | 0.7–1.2 | $0.005–0.008 | $0.135–0.138 | $0.120–0.123 |
| Per arrival in Cullet (whole cast) | 15–26 thoughts | $0.10–0.17 an arrival | — | — |
| Two settlements (ar2 stand-in) | 3.5–5.4 | $0.022–0.035 | $0.152–0.165 | $0.137–0.150 |
| City bound, gap 300 s | ≤ 12 | ≤ $0.078 | ≤ $0.21 | ≤ $0.19 |

**No fake run was made.** A free Cullet run would not firm up the event rate:
- The 7 real Cullet runs on this script already contain every first-sight line the rule would read, made with real movement.
- A fake model's plans move residents differently, so its counts would be less representative.
- The rule is not built, so a fake run could not test the throttle.
- Cullet has only one unplaceable person, so the city case cannot be reached on it either.

## 5. Verification plan (when built)

**verify-core** (`scenes.py first_sight`, new; features `sight.md` and `laws.md`):
- **Law off:** the crowd_sight scene's lines and no requests. Byte-identical lines to today.
- **Law on:**
  - an unknown U within making-out distance gives one first-sight line and one `deliberation` row whose reason is that line's unnamed part, exactly;
  - a known K seen first gives a line and no request;
  - U and K in one look give one line and a reason naming only U.
- **Far:** under the Cullet-like overlay of `stranger_filter` (far past 4 m), U at 5 m gives no line and no request. Within 4 m it gives both.
- **Throttle:**
  - within `think_min_s` of a thought, the request is refused, then taken at a later look while U is in sight;
  - it is settled with no second request when a thought with U in its scene happens first;
  - it is dropped when U leaves sight;
  - a second unknown within `first_sight_gap_s` asks nothing.
- **Re-arm:** "again after a long time" asks nothing. A `familiar` row deleted (forgetting) asks again.
- **Sleeper:** with the law on, an observer in a sleep act gives no line, no `familiar` row and no request. After it wakes, its first look gives both.
- **Laws:** `set_world_law` and read-back for both laws; `laws_about` words.
- **Unit tests:**
  - the reason is `first_sight_text` of the unnamed parts, and holds none of the rejected words (newcomer, visitor, arrival, new to you, near your home, worth);
  - the law defaults are off and 300.

**verify-minds** (real mind, fake model, Neo4j optional):
- a player W the resident does not know walks up, and the resident's next think request carries the first-sight reason and W in its scene;
- with `cues_on` and a `who: "unknown"` cue, one request carries both reasons, so one thought;
- a takeover with strangers in view gives exactly one thought (the takeover's);
- with `LIVING_RETHINK` set, the gate sees the reason and is not bypassed.

**verify-player:**
- a played character gets no first-sight line and no request, and its `seen_characters` label is still "a stranger";
- the player's join and walk make residents' requests (the trial's newcomer, scripted);
- refusals: `set_world_law` is refused to a player identity.

verify-client needs nothing: no table, view or reducer changes.

**A trial** (stage 3 of docs/STRANGERS.md, or its own small batch, once the owner decides). Cullet, the st2b script (stand, the Strand walk, the densest group).
- **Arms:** L against L + `first_sight_thinks`, and if cues stay on the table, LS + cues + `first_sight_thinks`.
- **Replicates:** 4 per arm, about $2.5–2.7 a run.
- **Measures:** the stage-2 table unchanged (in range, asks, approaches, inward, unaware, tells, first heard line, `converge_60s` and `together_4m`, re-asks, guards), plus:
  - per resident who saw the newcomer: request taken, merged, refused-then-taken, settled or dropped; seconds from first sight to the thought; whether that thought names the stranger;
  - Ingrid: a thought after the walk-by that mentions the newcomer, and a tell to Magda;
  - Aldous: a thought with the newcomer in its scene during his hours;
  - askers per run against the "5 or more" out-of-shape mark; residents asked within 10 s and within 60 s;
  - lines to the newcomer out of earshot;
  - deliberations and $ per resident-hour against L.
- **Expected,** from §3 and §4: inward rises, unaware falls, and the crowding marks are the risk.

## SpacetimeDB documentation

This design adds no table, column, view, reducer, subscription or index. It reads only what `noticed` and `request` already read:
- `familiar.by_actor_thing`;
- `deliberation.actor`, `mind_state.id` and `character.id` by primary key;
- `acquaintance.by_pair` and `membership.member` through `knows_name`, which `label_for` already calls for each first sight.

It writes `deliberation` rows through the existing path, so the mind service's existing subscription gets the same row kinds, and no client gets anything new. The owed set is thread-local, like `CUE_HELD`.

The documentation was not fetched again for this design. The pages docs/ATTENTION.md recorded for the cue design on 2026-11-12 apply ([indexes](https://spacetimedb.com/docs/tables/indexes/), [performance](https://spacetimedb.com/docs/tables/performance/), [access permissions](https://spacetimedb.com/docs/tables/access-permissions/); docs 2.0.0, pinned 2.14.1). The build must check them again if it changes any storage.
