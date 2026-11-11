# Mind feedback (feedback-1, 2026-11-10)

Status: **on branch `feedback-1`**, verified on the free tiers and by a small paid comparison. Seven defects from the trials ([trials](TRIALS.md), "What to evolve next", "Where it stalled or looped", "Architecture limits") and the [mind harness](MIND_HARNESS.md) defect list. Each item is either feedback the character can act on, true to what it perceives, or a fix to what a mind is sent. Nothing decides for a character (AGENTS.md, "no injected behaviour").

| # | Defect | What changed | Where |
| --- | --- | --- | --- |
| 1 | Minds never saw how their needs stood: the service did not subscribe to `vitals` | the service subscribes, as the owner, to the vitals of the characters it thinks for; think, compile and talk prompts say how the body feels, in words | `mind/src/main.rs`, `mind.rs` `body_now`, `prompts.rs` `felt_body`, `talk.rs`, `judge.rs` |
| 2 | A newcomer noticed one gate 24 times on arrival (one percept per gate tile) | touching new tiles of one kind and owner are one structure, noticed once with its extent | `authority/src/brain.rs` `noticed`, `joined_tiles` |
| 3 | Minds re-asked residents who never answered | not built: with layer 2 the loop no longer appears (below) | – |
| 4 | The phantom map: plans failed at remembered things | an `{"id": n}` target now resolves the structures and resources the scene lists by id, so the authority stops saying a thing in reach is "not in sight"; a failure at a thing named by id weakens what the mind remembers of it before it next thinks, and the reason says so | `authority/src/brain.rs` `visible_thing`; `mind/src/memory.rs` `weaken`, `failed_at_thing`; `mind.rs` `weaken_missed` |
| 5 | People heard each other say the word "text" | the grammar's own placeholder (`{"say": "text"}`) was copied into graphs; the example is now `"<the words>"`, and a say node or speech whose words are a format placeholder is pruned with a path-precise warning (graphs) or not spoken (replies) | `rules/src/normalize.rs` `placeholder_words`, `spoken`; `mind/src/prompts.rs`; `mind.rs`, `talk.rs` |
| 6 | Every long life grew "the ache for a child of my own" with no one to have one with | the consolidation prompt's identity sentence now says identity follows the life lived, and a feeling that comes and goes belongs to mood and memory until the life gives it someone or something to turn to | `mind/src/prompts.rs` `consolidate_system` |
| 7 | A death record named the killer by their real name | `character.cause` names the killer as the victim knew them (`perceived_of`) | `authority/src/act.rs` |

## SpacetimeDB documentation consulted (2026-11-10)

Pinned versions: server `clockworklabs/spacetime:v2.14.1` (the trial and verify containers), SDK `spacetimedb-sdk` as in `living/Cargo.lock` (the mind's subscriptions were already raw SQL).

| Page | What it says | Design implication |
| --- | --- | --- |
| [Tables](https://spacetimedb.com/docs/tables/) | "Private tables: Visible only to reducers and the database owner. Clients cannot access them." | The mind service connects with the owner's token (it is the world admin) and already subscribes this way to private `presence`, `woken` and `acquaintance`. `vitals` stays private. |
| [Access permissions](https://spacetimedb.com/docs/tables/access-permissions) | "Clients cannot query, subscribe to, or see private tables"; views read private tables and filter by `ctx.sender()`. | The owner path is not documented beyond the line above, so it was verified against the running 2.14.1 service: the join subscription applied in the fake run `fbdry` and in all six paid runs. Players keep `my_vitals`, a view that leaves out AI characters. |
| [SQL reference, subscriptions](https://spacetimedb.com/docs/reference/sql) | At most two tables per join; the query returns whole rows of one table; "subscriptions require an index to be defined on both join columns"; `WHERE` may filter the joined table. | `SELECT vitals.* FROM vitals JOIN character ON vitals.id = character.id WHERE character.controller = 0x… AND character.ai = true`: both join columns are primary keys. |
| [Subscriptions](https://spacetimedb.com/docs/clients/subscriptions/), [semantics](https://spacetimedb.com/docs/clients/subscriptions/semantics) | A transaction sends zero or one update, holding only the rows it inserted or deleted; overlapping queries cost twice; split data by update frequency. | Only rows of the service's own characters are sent, and only when written. The query does not overlap another `vitals` query. |

**The data path.** Rows read: one `vitals` row per character the service thinks for, joined on `character` (which it already subscribes to whole). Writes: none; the authority writes `vitals` only when a body's need rates change (night, rain, sleep, a fire or shelter, a hunger or energy threshold), when it eats or when it is hurt. Needs move linearly between writes, and the service computes them at the moment of a prompt from the row's rates, as `common::needs` does in the authority. Recipient: the mind service only. Update frequency: per character, a few rate changes a game hour, plus meals and blows. In a life trial (one newcomer plus the residents it wakes) that is a handful of characters. A resident's row joins the subscription when it wakes (`ai` turns true). Retained data: none beyond the client cache. The instinct-only island (about 300 characters and animals) is not sent.

## 1. The body in prompts

Think, compile and talk prompts carry one line, after the clock or under "Now":

```
How your body feels: very hungry, exhausted, badly wounded; you are growing weaker
```

Since 2026-11-11 (`rules-senses-outcomes`) the words and their thresholds are the world's `status_of` law, which the authority's bodily alarms and the players' screens read too ([world rules, "The body: meters and statuses"](WORLD_RULES.md#the-body-meters-and-statuses)); the shipped law keeps the thresholds this line had: hungry above 55, very hungry from 80, starving from 97; exhausted below 12 energy; hurt below 60% of full health, badly wounded below 35%, barely alive below 15%, and adds "rested" between 50 and 85 energy. The trend is the health rate's sign. The line has no numbers: the deliberation scene keeps its raw `health`, `hunger` and `energy` (the graph grammar's conditions are numeric). Consolidation and internalization prompts do not carry it. The routines list now shows "how that need stands now" (`repertoire_text`), and a judgment request reads the body at its moment instead of the last scene's.

**Tokens added**, counted by the provider (a request with and without the line, `max_tokens` 1): 11 tokens for the common "not hungry, unhurt", 13 for "hungry, tired, a little hurt", 22 for the longest ("starving, your body wasting away, exhausted, badly wounded; you are growing weaker"), the same on DeepSeek V4.1 Flash and GLM 5.3 Flash. Per deliberation (think and compile) that is 22–44 tokens, about 0.3% of a think prompt (p50 about 4,000) and 0.1% of a compile prompt (p50 about 11,000); a talk turn adds 11–22 to about 1,750. In the paid branch runs all think, compile and talk requests carried it.

## 2. One notice per structure

The island's first gate is not a row but a block of 24 gate tiles, about 7 by 8 (read from `verify-trial-fbbase-…-r1`). Each tile is its own `structure` row, and `noticed` announced each one. Now new tiles of one kind and owner that touch (within 1.5 tiles) are one structure: one percept with its extent, at the nearest tile ("You notice a gate about 7 by 8 tiles, 6 tiles southwest."), and nothing when part of it was already familiar (more of a known gate coming into view). Every tile still gets its familiarity row. The grouping runs only when something unfamiliar is in sight, so the 1 Hz path is unchanged.

Evidence: unit test `brain::tests::a_row_of_gate_tiles_is_one_gate` (the island's 24 tiles; two gates apart; neighbouring campfires of two builders stay two). In the paid runs a newcomer's percepts held 24 gate lines in its first five minutes on base and 1 on the branch, in every replicate.

## 3. Asking loops: checked, not built

The trials' loop was 100–182 lines to instinct-only residents who never answered. With layer 2 a resident the newcomer speaks to wakes and answers. Before building anything, the base arm was measured from the chronicle (`fbreport.py`): an ask counts as unanswered while the addressee has said nothing since, and it is "in earshot" when no `silence` percept ("No answer from …; they don't seem to be within earshot") came back for it.

| Base, 3 × 30 min | mean (range) |
| --- | --- |
| answers to the newcomer | 8.3 (6–10) |
| re-asks, in earshot, to someone who had never answered | 0.33 (0–1) |
| asks out of earshot (the authority already says so) | 2.0 (0–5) |
| lines to no one in particular | 5.0 (0–8); a repeat already gets "You said almost the same thing …" |

The loop the feedback was meant for does not happen any more: one re-ask in three runs. Unanswered streaks that remain are lines inside live conversations (a resident watching the newcomer mend a strap, then answering) and calls to people out of earshot, which already get truthful feedback. Nothing was built; the branch arm shows 0 in-earshot re-asks to the silent.

## 4. The phantom map

**What the base runs showed.** In 3 × 30 minutes on base, the newcomer's steps failed at things named by id 9.3 times per run (2–16), and **7.7 of those (82%) were at things in sight**: the authority said "no #66219 in sight" of a full berry bush 1.2 tiles away and "no #115 in sight" of a house 9 tiles away. The deliberation scene lists resources and structures with ids, the grammar teaches `{"id": n}` as a target, and `Target::Id` resolved only creatures. The authority's feedback was false, and the minds learned from it that their map was phantom ("My entire eastern map is phantom", in the trials).

**What changed.**
- `brain.rs` `sensed`: `{"id": n}` resolves a creature first (as before), else a structure or a resource in sight (`visible_thing`). An id names several things across tables (`#115` was a house, a far-off tree and a character); only things in sight count, creatures first. A depleted bush resolves, so the gather rule answers in its own words ("gather → #89035: the berry_bush is depleted"); only a thing out of sight is "no #n in sight".
- The mind service, before a deliberation, reads the character's new act failures that name a thing by id and say it was not there or bare (`memory::failed_at_thing`). It halves the salience of the concepts and memories naming that id, and the confidence of their open, fading edges (`Store::weaken`; durable edges such as `KNOWS` and kinship are untouched, nothing is retracted). The reason for thinking then says, in the character's terms: "(You went by what you remembered of #n, and it was not there to act on where you were; that memory feels less sure now.)" A creature's id is skipped: someone out of sight has not gone anywhere a memory should doubt (the first branch arm, `fbbr`, weakened people's memories this way; fixed before `fbbr2`).
- Weakening is memory dynamics, like fading. Nothing forbids a plan, and the next deliberation decides.

**Evidence.** Neo4j test `missed_things_weaken` (`verify-knowledge`): two concepts naming `#66219` lose half, `#662190` and `KNOWS` do not. `verify-minds` `acts`: a gather at the nearest resource by id goes ahead ("You did what you had decided: gather → boulder (+1 stone)"). The paid comparison is below.

## 5. The word "text" spoken aloud

`docs/MODEL_COST.md` flagged sample `talk-00` (Pim, `aske-coast-1792435287`), whose conversation shows the other speaker's lines as `“text”`. The talk prompt rendered the lines faithfully. The speech percepts themselves read `Fen said to Gwen: “text”`, and Fen's compile reply holds `{"say": "text", "to": 49}` (`Fen.jsonl:22`): a copy of the grammar's own example line, `{"say": "text", "to": T}`. In the Spark's trial journals, 32 of 13,294 think, compile and talk replies (0.24%, 18 journals) wrote a placeholder `say`.

Fix: the grammar's example is now `{"say": "<the words>", "to": T}`, and `normalize::spoken` refuses a say node whose words are a format placeholder (`text`, `words`, `the words`, `your words`, `what you say`, `message`, `...`, empty, with brackets and quotes stripped). The node is pruned with a path-precise warning ("first[0].then.seq[0].say: \"text\" is the format's placeholder, not words; write the words to say"), which the next deliberation is shown like any other pruned branch. A reply's own `say` (deliberation or talk) with placeholder words is not spoken. Unit test `placeholder_speech_is_pruned_with_its_reason` (Fen's graph; "Text me when you are back" still speaks). No placeholder appeared in the six paid runs, which is expected at 0.24%.

## 6. Wants that follow the life lived

The longing is a bodily drive the authority words once a game day at dawn ("You long for a child of your own.", `brain.rs`; iteration 3 found the counts were an artefact). What turned it into an identity is consolidation, whose only guidance was "Identity … changes only when experiences genuinely warrant it". The sentence now continues: "When it changes, it follows the life the person has lived: goals and values grow out of what they did, tried, met and went through, and name the people, places and things in that life they are about; a feeling that comes and goes (restlessness, loneliness, a longing) is felt, and belongs to mood and memory until the person's life gives it someone or something to turn to." No rule suppresses anything: a life with a partner, a child seen or a promise gives the feeling something to turn to.

**Replays.** The five moments, one per long life, where the identity first took on the want (`l1/life-deepseek-flash-r1/journal/Arlen.jsonl:27`, `l1/life-default-r1:29`, `l1/life-glm-flash-low-r1:76`, `l2/life-ruin-glm-flash-low-r1:94`, `l3/life-pressure-glm-flash-low-r2:74`, on the Spark), each sent four times with the recorded system prompt and four times with the new sentence, same model and parameters as recorded (`replay_wants.py`, scratch):

| Wording | Replies | Identity changed | Child in goals or values | Child in narrative |
| --- | ---: | ---: | ---: | ---: |
| recorded (two samplings) | 40 | 29 | 19 (66%) | 26 |
| first draft ("Identity follows …", always) | 20 | 20 | 6 (30%) | 13 |
| **shipped ("When it changes, it follows …")** | 20 | 15 | **3 (20%)** | 11 |

The first draft also made the model rewrite identity every time (0 of 20 left it null, against 11 of 40); the shipped wording keeps the null rate (5 of 20). One replay, before and after (`l1/life-default-r1:29`): before, goals ended "found a settlement of my own one day | have a child of my own and pass my trades on" and the narrative had "a new ache under the ambition: a child of my own"; after, the goals ended "found a settlement of my own one day | keep my temper leashed until it pays" and the narrative "someday a settlement of my own with me at its head". The feeling stayed in the experience and the memory. The 30-minute paid runs are too short to show it (each arm wrote one such identity among 16–22).

## 7. The death record names what the victim knew

`act.rs` wrote `character.cause = "killed by <real name>"`, and a player's death screen reads it through `my_characters`, so a newcomer killed by a road wolf read "killed by Storm the wolf" (verify-player, earlier run). The killing blow now writes the killer as the victim perceived them (`common::label_for` with the victim as observer, the `perceived_of` projection), before death clears the victim's rows. The chronicle's `killing` and `death` rows keep real names (audit truth). Tools that read `cause` match only its `killed by` prefix, which is unchanged.

Evidence: `verify-player` `combat.py` on a scratch island (`player-fb1-012517`): a resident the player killed is recorded "killed by a stranger" (no `acquaintance` row) while the chronicle reads "FbPlayer killed Kelhan"; the player killed by the bold pack is recorded "killed by a wolf".

## The paid check

**Setup.** One newcomer for 30 real minutes (60 game hours) on the shipped island with town life layer 2 (`life-social` cut to 30 minutes, `LIVING_ONLY=<newcomer>,woken`), variant `deepseek-flash` (DeepSeek V4.1 Flash for the newcomer; woken residents on the models file's `woken` route), 3 replicates per arm, one world seed. Run on the Mac with `trials.py`, each arm on its own SpacetimeDB 2.14.1 and Neo4j containers (`feedback-base-*` on 3341/7721, `feedback-br-*` on 3342/7722), its own worktree and target directory. Base is `origin/main` 6de2bad. `fbbr` is the branch before people were excluded from weakening; `fbbr2` is the branch as committed (ffb4280). The arms ran one after another (base 23:35–00:06 UTC, `fbbr` 23:53–00:24, `fbbr2` 00:25–00:56), so provider conditions differ by up to an hour; verification builds ran at low priority alongside `fbbr` and `fbbr2`. Measures come from the evidence only (`living/tools/feedback_report.py`; positions of failed-at ids were cached while the worlds lived, `feedback_idpos.py`).

| Mean (range), 3 runs each | base (`fbbase`) | branch, first (`fbbr`) | **branch (`fbbr2`)** |
|---|---|---|---|
| real minutes | 30.00 (30.0–30.0) | 30.00 (30.0–30.0) | 30.00 (30.0–30.0) |
| game hours | 60.00 (60.0–60.0) | 60.03 (60.0–60.1) | 60.03 (60.0–60.1) |
| deliberations | 31.67 (22–48) | 34.00 (24–48) | 28.67 (27–30) |
| **deliberations per game hour** | 0.53 (0.37–0.8) | 0.57 (0.4–0.8) | 0.48 (0.45–0.5) |
| lines addressed to someone | 20.33 (14–26) | 18.67 (6–32) | 12.33 (12–13) |
| lines to no one in particular | 5.00 (0–8) | 5.67 (1–10) | 3.00 (0–6) |
| re-asks while the last ask was unanswered (any, incl. live talk) | 10.33 (7–14) | 7.00 (1–15) | 3.33 (2–4) |
| longest unanswered streak | 5.67 (3–7) | 3.00 (2–4) | 2.33 (2–3) |
| **re-asks in earshot to someone who never answered** | 0.33 (0–1) | 0.00 (0–0) | 0.00 (0–0) |
| asks out of earshot | 2.00 (0–5) | 3.33 (0–10) | 3.67 (0–10) |
| answers to the newcomer | 8.33 (6–10) | 10.33 (5–16) | 6.00 (2–9) |
| acts toward the newcomer (chronicled) | 0.33 (0–1) | 0.00 (0–0) | 0.00 (0–0) |
| **failed steps at things named by id** | 8.33 (1–14) | 0.67 (0–1) | 1.00 (0–3) |
| **… at a thing in sight (false feedback)** | 7.67 (1–12) | 0.00 (0–0) | 0.00 (0–0) |
| failed steps at people who had walked off | 1.00 (0–2) | 1.00 (0–2) | 2.67 (0–7) |
| gate percepts | 24.00 (24–24) | 1.00 (1–1) | 1.00 (1–1) |
| **gate percepts, first 5 minutes** | 24.00 (24–24) | 1.00 (1–1) | 1.00 (1–1) |
| lines “text” | 0.00 (0–0) | 0.00 (0–0) | 0.00 (0–0) |
| residents woken | 10.00 (7–12) | 9.00 (6–13) | 9.67 (7–15) |
| calls, newcomer | 79.00 (59–113) | 82.00 (59–110) | 73.67 (73–75) |
| **tokens, newcomer** | 606650.67 (417480–915565) | 640379.00 (418818–929100) | 540240.33 (530090–560401) |
| calls, woken residents | 305.00 (284–316) | 216.00 (119–331) | 296.67 (147–545) |
| tokens, woken residents | 2276273.00 (2209283–2313145) | 1478297.00 (839209–2148435) | 2057761.67 (1059355–3602556) |
| cost per run (USD) | 0.60 (0.559–0.67) | 0.44 (0.257–0.648) | 0.52 (0.334–0.775) |
| alive at end | 3/3 | 3/3 | 3/3 |

**Reading it.**
- **Phantom map:** failed steps at things fell from 8.3 to 0.7–1.0 per run, and none of the remaining ones was at a thing in sight (base: 7.7 were). What remains is true: a thing out of sight, a bush picked bare ("the berry_bush is depleted"), a full pack. Steps toward people who walked off (1.0 against 1.0 and 2.7, mostly one run of `fbbr2` following residents) are not phantom memory and are not weakened.
- **Gate:** one percept instead of 24, in every run.
- **Asking:** no arm re-asked a silent person in earshot more than once; the loop is gone with layer 2 (item 3).
- **Deliberations per game hour:** 0.53 (0.37–0.80) on base, 0.57 and 0.48 on the branch: no change beyond the spread. The body line and the weakening note add no deliberations.
- **Tokens:** the newcomer used 607k on base and 640k and 540k on the branch, within one another's ranges. Woken residents dominate the cost and vary with how many were woken and how long they talked (0.84–3.6M per run); that is town life, not this branch.
- **Outcomes:** every newcomer lived the 30 minutes in every arm, and residents woke and answered in all of them (base 8.3 answers per run, branch 10.3 and 6.0). Thirty minutes is too short for learning, building or the identity drift of item 6; those rest on the replays.

**Spend:** base $1.79 (8.6M tokens, 1,152 calls), `fbbr` $1.33 (6.4M, 894), `fbbr2` $1.57 (7.8M, 1,111); the identity replays $0.11 (80 calls, 449k tokens); the token count for item 1 a few cents' fraction. **Total about $4.80**, at the Mistral prices in [trials](TRIALS.md#tokens-and-cost).

## Verification

| Surface | Run | Result |
| --- | --- | --- |
| `verify-minds` | `minds-fb1-005416` (all cases) on `feedback-verify-stdb` (3343) | 14 pass, `consolidation` the known XFAIL; `acts` failed on the new check's wait (it waited for `#id` in the outcome, which names the kind) and passed after the fix (`minds-fb1acts-011707`). `roundtrip` asserts the body line in the think and compile requests; `acts` asserts a gather at a resource id goes ahead. |
| `verify-knowledge` | `knowledge-fb1-011838` | 19 of 19, including the new `missed_things_weaken` |
| `verify-knowledge` `woken_mind.py` | `knowledge-woken-fb1b-…` | 8 of 8; the first attempt failed because the script hardcoded `:3300` for the mind (fixed: it reads `LIVING_STDB_URL` like its siblings) |
| `verify-player` `combat.py` | `player-fb1-012517` (island), scenes `kill` and `death` | 5 of 5: "killed by a stranger", chronicle "FbPlayer killed Kelhan"; "killed by a wolf" |
| Cargo | `just living-check` (private target) | pass |
| Paid | `fbbase`, `fbbr`, `fbbr2` above | – |

Not covered: `verify-client` (no table, reducer or view changed; `vitals` stays private and the new query is the owner's; a player's attempt at the same join was not driven), `verify-core` scenes (the id resolution and the gate grouping are covered by unit tests and the minds and trials runs above), `verify-generation` and `verify-llm` (untouched). These runs do not establish performance or scale.

## Files

`living/mind/src/{main.rs, mind.rs, prompts.rs, memory.rs, mind/talk.rs, mind/judge.rs, mind/lived.rs}`, `living/authority/src/{brain.rs, act.rs}`, `living/rules/src/normalize.rs`; tools `living/tools/{feedback_report.py, feedback_idpos.py, replay_wants.py}`. Shared files other branches touch: `mind.rs` (deliberate, a few lines before recall), `prompts.rs` (the grammar's say line, the consolidation identity sentence, `Ctx`/`TalkUser` gained a `body` field), `judge.rs` (the body in the judgment state), `brain.rs` (`noticed`, `sensed`).
