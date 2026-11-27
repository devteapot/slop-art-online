# Truthful refusals (truthful-refusals, 2026-11-22)

A refusal says what actually happened. Before this change every target that did not resolve, for a player's `human_act`, a mind's `mind_act`/`mind_act_checked` and a graph leaf alike, was told "no … in sight", whatever the cause; and what was not an act at all was refused in the graph parser's words. Found by the battle-frame diagnosis of the act trial ([INPUT_LATENCY.md](INPUT_LATENCY.md#real-model-trial-act-trial-2026-11-21); branch `battle-frame`'s `docs/FAST_LANE_FRAME.md` §1: 29% of refused acts named a place the authority does not know, 19% were not acts); same rules for players and minds. The act-trial journals read here are battle-frame's extracted copies of `~/slop-evidence/act-trial-20261121.tar.zst`.

## What the act trial showed (read only)

Act-trial battle arms `minds-atb1-off-055246` / `minds-atb1-on-060222` (minutes 2–8), each refused `{"place": name}` matched to its compile prompt:

- **No battle prompt held a single named place.** All 2,033 / 2,048 compile prompts' "# Places you remember" were remembered resources (`seen_stock`: "8 berry bush around [x, y]: seen …"), about 6,700 lines. The grammar said `{"place": "name of a place you remember"}` and "places and coordinates always resolve", so the minds copied those lines, or their kinds, as place names. 7 / 4 place acts resolved.
- Of 380 / 355 unknown-place refusals: `"home"` (the prompt's own example; fighters have no "home" row) 32 / 31; from the remembered-resources list (a line copied or reworded, or its kind) 100 / 75; something in sight named as a place 28 / 45; directions and roads ("south", "north along the road", "road") 120 / 118; other kinds, coordinates and names the rest.
- **Directions:** 130 / 144 of the refused names held a compass word or "road"; 113 / 115 a compass word and no coordinates. No direction target is built here.
- In the town arms, where people hold named places, 24 of 892 refusals were unknown places.

Heard-of and visited places are both `place` rows (a seed's `towns_known`, a background's places, a mind's own projection), with no flag between them, and the prompt does not separate them. Resolution reads only the actor's own rows at the coordinates each row holds, so a place one was told of goes where one was told it is, never to the world's own place by that name. That stays exactly as it was.

## The rule

`Ev::unresolved` (`living/authority/src/brain.rs`) says why a target did not resolve, read only from what the character holds or perceives; `resolve_for` returns it (`Err((code, why))`), the act path tells it (`acts.rs` `next_reporting`) and the graph's `do` and `say` leaves fail with it.

| Target | Why, as told | Code (`act_outcome`) |
| --- | --- | --- |
| `{"place": name}` not among one's own rows | you know no place called "name" | `unknown` (new) |
| `attacker`, `speaker`, `hailer` with nobody in the last minute | nobody has hurt / spoken to / greeted you in the last minute | `unknown` |
| `suitor`, `partner`, `parent` with none | nobody has offered to start a family with you lately; you have no partner (the other parent of your youngest child); you have no parent | `unknown` |
| `sound` with nothing heard | you hear nothing you cannot see | `unknown` |
| the same roles, filled but out of sight | whoever hurt you / spoke to you / greeted you … is not in sight; your partner is not in sight | `unseen` |
| `{"id": n}`, dead and its remains in sight | #n is dead: their remains lie in sight | `refused` |
| `{"id": n}` otherwise (a death out of sight included) | no #n in sight | `unseen` |
| `{"nearest": resource}`, some in sight but all bare | every berry bush in sight is bare | `refused` |
| `{"named": name}` | you see no one you know as name | `unseen` |
| anything else | no … in sight | `unseen` |

**A leaf's activity under way that loses its target** (give-out-of-sight-line, 2026-11-26). A graph's `do` leaf looks for its target again at each evaluation. When its own activity is being performed (an approach goes by the last-seen place until steering loses it, "lost sight of them") and the target no longer resolves, the leaf breaks the activity off and tells it like any failure after starting (`act::lost`: `You failed to <action>: <why>`, once per `repeat_failure_s`, to a player as to an AI, counted against its routine). Out of sight it says steering's words, "lost sight of them" (or "lost sight of it"), with code `unseen`; any other reason in the table's words and code. Before, the evaluator dropped the activity without a word (only `stuck: give: no #N in sight` in the record) unless the activity's own timer fired first ("they moved away"). A committed move runs its course as before; a branch losing priority or a new plan replacing the activity stays untold, since the character chose it. A deliberate act is not re-resolved: its completion tells it ("they moved away").

`{"place": "home"}` is one's own home, as the `home` target is: one's own "home" row, else one's own home position (`Target::Home`), never anyone else's. The prompts' own examples use it, and fighters without a "home" row were refused it.

**Not acts** (`living_rules::acts::parse`, code `unreadable` as before), named for what they are: "`say` is speech, not an act: speak it instead"; "`wait` is a behavior-graph node, not a one-off act: an act is one {"do": skill, ...}" (any graph node: first, seq, if, wait, think, routine, desires); "`call` is not a skill, so not an act"; "`act`: neither a skill nor a behavior-graph node, so not an act: …". A player's `human_act` still makes a non-act node its command graph, as before.

**Cost.** The why is worked out only after a target failed. Role and place causes read a field or one indexed `place` filter; the bare check reads the resources already gathered for the failed `nearest`; the dead check looks up one character and, only if it is dead, the structures in sight. A `nearest` creature with a relation is not re-scanned (it stays "no … in sight"), so a scene-lazy fighter's failing leaf gathers nothing more.

**Clients.** `act_outcome.code` gains the value `unknown` (appended to `ACT_CODES`; `the_codes_only_grow`). No table, column, index, view, reducer or subscription changed; SpacetimeDB use is unchanged, so no new pattern was needed. The game client maps no act code to words or icons: `living/game/src/verbs.rs` `outcome_of` shows the row's `why` for any refused code and only treats `moved` apart; the browser viewer reads no outcome codes.

## The prompt

- The graph grammar (compile and fast lane): `{"place": "a quoted name under Places you remember"}`, and "A place resolves only by a quoted name under Places you remember ("home" is your own home); coordinates always resolve: reach a resource listed under Resources you have seen, or any spot, with {"at": [x, y]}." (was "places and coordinates always resolve").
- `Minds::places` returns named places and remembered resources apart. Think, compile, consolidation and player memory prompts list "# Places you remember" (named places only) and, when there are any, "# Resources you have seen (not places: reach one with {"at": [x, y]})"; a talk turn lists "# Places you know[, from where you stand]" and "# Resources you have seen[, from where you stand]". The lines themselves are unchanged.
- The resources section is the existing `STOCK_SHOWN` cap, 8 lines: the nearest to the scene's own place (`you.at`) for think and compile, the nearest to where one stands for a talk turn, the latest seen for consolidation and player memory. It cannot grow in a battle. It is now a dynamic segment (it changes with where one stands), so the character segment before it caches better.

Measured on saved act-trial prompts, each rebuilt with this change's exact text (prompt tokens from the call's own count, the change scaled at that call's own characters per token; no tokenizer was installed on the Spark):

| Prompt | Places / resources | Characters | Prompt tokens |
| --- | --- | --- | --- |
| Battle compile (Walker1, `minds-atb1-off`) | 0 / 8 | 54,792 → 55,051 (+259) | 14,791 → ~14,861 (+70, +0.5%) |
| Town compile (Cecily Carter, `at1off`) | 24 / 8 | 61,368 → 61,620 (+252) | 16,989 → ~17,059 (+70, +0.4%) |
| Battle think | 0 / 8 | 15,799 → 15,877 (+78) | 4,387 → ~4,409 (+22) |
| Town think | 24 / 8 | 21,540 → 21,611 (+71) | 6,129 → ~6,149 (+20) |

## Verification

- `living-rules` `acts::tests::acts_are_single_do_nodes` (each non-act named), `outcome::tests::the_codes_only_grow`; `living-mind` `prompts::tests::places_and_seen_resources_are_apart`.
- verify-core `scenes.py truthful_refusals` (each refusal kind beside a control, through `mind_act` and graph leaves); verify-player `refusals.py` (the codes in `my_act_outcomes` through `human_act`); verify-minds `talk-places`, `act-repair`, `acts`.
- give-out-of-sight-line: `living-authority` `brain::tests::a_lost_target_is_told_what_happened`; verify-player `told.py` part 3 (a gift whose receiver is moved 20 m while it is handed over: a command, a graph and a deliberate act, player and AI, exactly one line each).
