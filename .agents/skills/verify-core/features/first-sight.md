# First sights that ask for a thought

A first sight of someone one cannot place asks one's mind for one thought (docs/FIRST_SIGHT.md). The law `first_sight_thinks` is off by default; `first_sight_gap_s` is 300 s (0–3,600). Both are script laws (`skills.rhai` `laws()`, `script.rs` `Laws`), switched at runtime by `set_world_law` and described by `laws_about`.

## What it does (user POV)

- **Can't place.** A person (or one of one's own kind) whose first-sight part is unnamed: not known by name (`perception::knows_name`) and not too far away to make out (`regard().far`). It is the test `noticed` already applies (`named = who == ch.name` from `common::label_for`). A far figure gets no first sight at all (far-label), so it never asks.
- **First sight.** No `familiar` row for `(observer, FAM_CREATURE | id)` when the person is made out. "Again after a long time" does not ask. A row forgotten under `FAMILIAR_LIMIT` (2,048 since `battle-scale`, by age only and never one in view: [battle.md](battle.md)) makes the next sight a first sight again.
- **The request** (`brain.rs` `first_sight_asks`). Its reason is `first_sight_text` over the look's unplaced parts only, the line's own words ("For the first time you see a stranger, 2 tiles east, wait."). It goes through `perceive::ask_to_think`, so the species' `think_min_s` refuses it right after a thought, and a pending request takes it as one more reason.
- **Owed.** A refused request is owed. It is tried again at later looks for at most 60 s (`FIRST_SIGHT_OWED_MS`), while the person is in sight and still cannot be placed. Any thought made since the first sight settles it.
- **The gap.** First sights bring a character to think at most once per `first_sight_gap_s`. Inside the gap a first sight only merges into a request already pending; otherwise it is dropped, not owed.
- **Sleepers.** With the law on, a sleeper (`perceive::asleep`) does not see someone it cannot place for the first time: no line, no `familiar` row, nothing in `slumber`. The person is looked at again every 5 s (`FAR_MARK`, as for a far figure). The first look after waking makes the first sight, and it asks.
- **Played characters** run no `noticed` (`if !self.me.ai`): no first-sight line, no request (verify-player `first_sight.py`).
- **With a cue.** `cues()` runs first in `noticed`. A cue on someone unknown that fires on the same person makes the pending request, and the first sight joins it: one request holding both lines.
- **State.** The gap and the owed set are thread-local (`FIRST_SIGHT`), lost on a module update; the first-sight lines are durable experiences. No table, column, view or reducer is added.

## How to verify

`scenes.py first_sight` (any seed, about 4 minutes). No mind runs, so `mind_skip` stands in for a thought: it clears the request and sets `deliberated_ms`. On an open line, O and eight spawned people, none familiar to O:

1. **Law off:** U1's first sight is told and asks nothing.
2. **On, refused:** right after a thought, U2's first sight is refused (`think_min_s` 20 s). It is asked again after 20 s: one request, whose reason equals the experience's text.
3. **The gap** (40 s): U3, seen past `think_min_s` but inside the gap, asks nothing, then or after the gap (dropped, not owed).
4. **Far and named.** Under an overlay of `perceived_of` that marks everyone past 4 m `far`, with the gap at 0:
   - V (unknown) at 6 m gets no first sight, no `familiar` row and no request;
   - K tells O its name from 7 m (`mind_say` "I am K."), then is brought within 4 m: a first sight naming K that asks nothing;
   - V within 4 m asks, its reason V's line alone.
5. **Once per first sight:** V away and back gives no line and no request.
6. **Sleeper:** O asleep (`{"do": "sleep"}`, `slumber` row). W at 2 m gets no line, no `familiar` row, nothing in `slumber` and no request. Woken, W's first sight is told and asks.
7. **Cue:** with `cues_on` and a cue on someone unknown, X's first sight and the cue's fire are one pending request holding both lines.

The laws, the script, O's cues and graph are restored at the end, even on failure.

```bash
python3 "$C/scenes.py" first_sight --run "$R" > ".local/living/verify/$R/first_sight.txt" 2>&1
```

Cargo:
- rules `script::tests::first_sight_thinks_is_the_world_s_law` (default off and 300 s, the world's values clamped, the words);
- authority `brain::tests::a_first_sight_asks_in_the_line_s_own_words` (the reason is `first_sight_text`, with none of the rejected newcomer laws' words).

Regressions with the law off: `crowd_sight`, `stranger_filter`, `cues`, `sleeper`, `sight`.
