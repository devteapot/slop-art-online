# Attention cues

What a mind wrote should bring it to think (docs/ATTENTION.md). The mind service projects a character's cues through `mind_update` (`MindUpdate.cues`, `mind.rs` `set_cues`); the authority keeps them in the private `cue` table (at most 8 a character) and matches them by type against what the character perceives, on its own evaluations (`brain.rs` `Ev::cues`, called from `noticed`).

## What it does (user POV)

- **Fields** (`Cue`): `for_key` (`stance:`, `project:` or `goal:` and a key), `why` (the mind's words), `who_id` (a person or creature by id), `who` (`unknown`: a person whose name one does not know; or a creature kind), `doing` and `phase` (what the matched creature is visibly doing and in which phase: `perception::visibly`, the row COMBAT_MIND 3.2's `doing` condition reads), `thing` (a resource or structure kind; a structure counts by its kind's `like` too), `at` (one of the actor's `place` rows, with `within`, default 20 m, at most 48), `near_me` (metres). Every field given must hold for the same perceived thing; `who` and `thing` do not mix.
- **Refusals** (`cue_refusal`): kept as a row with `refused` set, never matched: a `phase` that is not one of `living_rules::doing::Phase`'s words, a `for_key` serving nothing, nothing to watch for, `doing` with no doer, an id one never met (no `familiar` or `relation` row, name unknown), an unknown creature kind, skill, thing kind or place.
- **Matching** (`cues_on` law, off by default): at most once per `cue_check_s` (default 1 s) per AI character, over the evaluation's scene (creatures, resources, structures). Someone too far away to make out (`regard().far`) matches nothing, by id or kind. A thing fires when it *begins* to match (a thread-local edge, `CUE_HELD`), once per thing per `cue_cooldown_s` (`Cue.fired`, durable), and a character's cues bring it to think at most once per `cue_gap_s`; things that begin to match together go in one line.
- **A fire** asks the mind to think (`perceive::ask_to_think`) with the line as its reason; only when that request is taken (a mind is not refused within its species' `think_min_s`) is the fire recorded (`fired`, `fires`) and the `noticed` experience written (salience 0.65), in the observer's own labels and quoting the `why` verbatim: `You notice a stranger, 2 tiles southeast: you watch for this ("<why>").` A refused request retries at the next check.
- **The rethink gate** passes a cue's reason (`living/configs/rethink.json` `urgent`: `": you watch for this ("`).
- **Who keeps cues:** a character a person plays keeps none (`mind_update` writes an empty set for it). Death deletes them (`act::die`).

## Driving it

`scenes.py cues` (about 1.5 minutes, any seed). O founds a community and welcomes K; O's mind (`mind_update`, as the mind service) writes `who: unknown, at: verify yard within 20` with a fixture `why`, and the place.

1. Law off: N (unknown to O) at 2 m gives no `noticed` row and no fire.
2. `set_world_law cues_on true`, `cue_gap_s 15`: N coming in gives exactly one `noticed` row about N, quoting the `why` verbatim at salience 0.65, a `deliberation` row whose reason holds it, and `fires` 1 with N in `fired`.
3. N leaves and comes back within the cooldown: not told again. U (unknown) coming in at the same time is told only once 15 s have passed since N's fire; two lines in all.
4. An overlay of `perceived_of` makes everyone past 4 m `far`; the cues become `who: unknown` and `who_id: K` (O's community). V (unknown) and K at 6 m: nothing. V at 2 m: told.
5. Six cues the world cannot watch for are kept, each with its reason (an unknown place, phase, creature or thing kind, a deed with no doer, serving nothing); a cue on a wolf visibly winding up a strike is accepted; an empty set clears them.

The shipped script, `cues_on` off and `cue_gap_s` 60 are restored at the end. Evidence: `cues-deliberation-after-fire.json`, the run's `actions.log`. Rules test `script::tests::attention_cues_are_the_world_s_laws` (defaults, `law_about`, a world's values and clamps).

Not covered here: cues written by a real mind (verify-minds `cues_mind.py`), `thing`, `doing`/`phase` and `near_me` matches (the code only; `visibly` itself is driven by `doing_seen`), the cost at scale (docs/ATTENTION.md, "Cost").

## Shared answers

What each observer makes of each target is worked out once per transaction and shared by everyone who asks (`perception.rs` `with_answers`; the `regard_cache` law, on by default): whether it knows the target's name (`knows_name`), its own know-how as the `perceived_of` law reads it, and the law's answer by distance and time (`regard`). The askers are cues, the scene's labels and the far label (`project`, `scene_json`), far handles (`far::id_for`), first sights and graph filters (`brain.rs`), and told lines naming others (`label_for` → `labels`). Every write that can change an answer bumps a generation that empties the cache: acquaintance, membership, know-how, reveal, a new character or new parents (`answers_changed`). With `regard_cache` off every asker computes afresh (the code path before the cache).

`scenes.py regard_check` (about 4 minutes, any seed) turns on `regard_cache_check`, under which every cached answer is computed afresh too and any difference is logged (`regard cache: …`) and counted in the per-second line `regard answers: hits=… computed=… compared=… differed=… bumps=…`. It drives `crowd_sight`, `stranger_filter` (the far overlay), `cues`, and on an island run `outcomes` (told lines), then a fight among minded onlookers while one says its name to another (an acquaintance written mid-run). It passes when at least 1,000 answers were compared and none differed. Evidence: `regard_check-regard-check.json`.
